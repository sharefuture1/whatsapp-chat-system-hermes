# 数据模型规格

## 1. 通用规则

- **DATA-001**：production 必须使用 PostgreSQL；SQLite 仅限 test/开发单机（single-node），不得作为高并发生产数据库。
- **DATA-002**：所有表使用 UTC 时间；API 使用 ISO 8601。
- **DATA-003**：所有 WhatsApp 业务实体必须带 `account_id`。
- **DATA-004**：任何联系人、会话和消息查询都必须进行 account scope 限制。
- **DATA-005**：JSON 字段只存扩展元数据，不替代可查询的核心列。
- **DATA-006**：数据库迁移使用 Alembic，不允许生产启动时隐式破坏性建表。
- **DATA-007**：高频状态更新必须有索引；任务 claim 必须可并发安全。
- **DATA-008**：关系智能表必须以 `account_id` 为第一隔离边界，并同时保存适用的 `contact_id`、`conversation_id`；所有外键和查询均校验同账号，禁止跨账号关联。
- **DATA-009**：PostgreSQL 使用 JSONB；pgvector/向量索引是 optional。核心过滤、排序、游标和状态必须是普通列并建索引，hot path 禁止 JSON scan（扫描 JSON/JSONB 才得到过滤键）。

## 2. 核心表

### 2.1 `whatsapp_accounts`

```text
id                  UUID / stable slug PK
name                varchar not null
phone_number        varchar nullable
status              enum(new, qr_pending, connecting, online, offline, error, logged_out)
session_ref         varchar not null      # 引用，不保存凭据
is_primary          bool default false
enabled             bool default true
auto_reply_mode     enum(off, suggest, auto)
ai_profile_id       FK nullable
last_seen_at        timestamptz nullable
last_error_code     varchar nullable
last_error_message  text nullable
created_at          timestamptz
updated_at          timestamptz
```

约束：

- 同一租户最多一个 `is_primary=true`；
- `session_ref` 不得包含 session JSON 内容；
- `logged_out` 不允许自动无限重连。

### 2.2 `contacts`

```text
id             UUID PK
account_id     FK whatsapp_accounts not null
remote_jid     varchar not null
phone_number   varchar nullable
lid            varchar nullable
display_name   varchar
remark         varchar
notes          text
tags           json/array
language       varchar
avatar_url     text
metadata       json
created_at     timestamptz
updated_at     timestamptz
```

唯一约束：

```text
UNIQUE(account_id, remote_jid)
```

### 2.3 `conversations`

```text
id                    UUID PK
account_id            FK not null
contact_id            FK nullable
remote_jid            varchar not null
type                  enum(dm, group)
title                 varchar
last_message_at       timestamptz
last_message_preview  text
unread_count          int default 0
pinned                bool default false
muted                 bool default false
archived              bool default false
deleted_at            timestamptz nullable
assigned_operator_id  FK nullable
ai_mode               enum(off, suggest, auto)
created_at/updated_at  timestamptz
```

唯一约束：

```text
UNIQUE(account_id, remote_jid)
```

索引：

```text
(account_id, archived, last_message_at DESC)
(account_id, pinned, last_message_at DESC)
(account_id, unread_count)
```

### 2.4 `messages`

```text
id                 UUID PK
account_id         FK not null
conversation_id    FK not null
contact_id         FK nullable
wa_message_id      varchar nullable
direction          enum(inbound, outbound)
sender_jid         varchar
message_type       enum(text, image, audio, video, document, system)
content            text
media_metadata     json
quoted_message_id  UUID nullable
status             enum(received, queued, sending, sent, delivered, read, failed)
error_code         varchar nullable
error_message      text nullable
retry_count        int default 0
created_at         timestamptz
sent_at             timestamptz nullable
delivered_at       timestamptz nullable
read_at            timestamptz nullable
```

唯一约束：

```text
UNIQUE(account_id, wa_message_id) WHERE wa_message_id IS NOT NULL
```

索引：

```text
(conversation_id, created_at DESC, id DESC)
(account_id, status, created_at)
```

### 2.5 `whatsapp_events`

```text
id            UUID PK
event_id      varchar not null
account_id    FK not null
event_type    varchar not null
occurred_at   timestamptz
sequence      bigint not null
payload       json
payload_hash  varchar not null
processed_at  timestamptz
status        enum(received, processed, failed)
error         text nullable
```

用于 webhook 幂等和审计。

约束与处理规则：

```text
UNIQUE(account_id, event_id)
INDEX(account_id, sequence)
```

- 相同账号/event_id 只有 payload hash 一致时才算 duplicate；
- 状态事件按账号 sequence 单调应用，迟到事件不得回退账号状态；
- `message.upsert` 在同一事务内 upsert contact/conversation/message 并标记事件 processed；
- 所有关联写入必须验证 contact/conversation/message 的 account_id 一致，禁止跨账号外键引用；
- 账号业务删除时事件保留策略必须由归档/审计流程执行，不得无提示清除证据。

### 2.6 `ai_profiles`

```text
id                UUID PK
name              varchar
provider          varchar default wendingai
base_url          varchar default https://wendingai.future1.us/v1
default_model     varchar default gpt-5.3-codex-spark
system_prompt     text
reply_style       text
temperature       decimal
timeout_seconds   int default 90
max_retries       int default 2
enabled           bool default true
created_at/updated_at
```

API key 默认从 secret 环境引用，也可由管理员在设置页更新后以应用层加密密文保存；任何表、API、日志均不得出现明文。加密主密钥只能来自 `AI_SECRET_ENCRYPTION_KEY`/Secret Manager，不得与密文存放在同一数据库。数据库中的自定义模型和密钥密文覆盖环境变量，无数据库覆盖时回退环境配置。

### 2.6.1 `ai_runtime_settings`

```text
id                    varchar PK = global
provider              varchar default wendingai
base_url              varchar default https://wendingai.future1.us/v1
default_model         varchar default gpt-5.3-codex-spark
api_key_ciphertext    text nullable
api_key_hint          varchar nullable      # 仅脱敏尾号，不可反推密钥
updated_by            varchar nullable
created_at/updated_at timestamptz
```

规则：

- `api_key_ciphertext` 必须使用认证加密，禁止自行 Base64/哈希冒充加密；
- GET 接口不得返回 `api_key_ciphertext`；
- 空 key 更新表示保留原值，显式清除必须独立动作并二次确认；
- 每次更新写 `audit_logs`；
- 更新后刷新内存配置，使下一次 AI 请求立即使用新模型/key。

### 2.7 `contact_ai_overrides`

```text
account_id         FK
contact_id         FK
model              varchar nullable
system_prompt      text nullable
reply_style        text nullable
language           varchar nullable
auto_reply_enabled bool nullable
PRIMARY KEY(account_id, contact_id)
```

### 2.8 `outbox_messages`

```text
id               UUID PK
message_id       FK messages unique
account_id       FK
idempotency_key  varchar unique
status           enum(pending, claimed, completed, failed, dead)
attempts         int
available_at     timestamptz
lease_owner      varchar nullable
lease_expires_at timestamptz nullable
last_error       text nullable
created_at/updated_at
```

### 2.9 定时与群发

`scheduled_messages`：

```text
id, account_id, conversation_id/target_jid, content, run_at,
status(pending, claimed, sent, failed, cancelled),
idempotency_key, lease_owner, lease_expires_at, last_error
```

`broadcast_jobs`：

```text
id, account_id, content, status(draft, queued, running, paused, completed, failed, cancelled),
total_count, queued_count, sent_count, failed_count, created_by, created_at
```

`broadcast_recipients`：

```text
id, job_id, contact_id/target_jid, status, attempts, wa_message_id,
last_error, sent_at
UNIQUE(job_id, contact_id/target_jid)
```

### 2.10 插件与审计

`plugin_states`：

```text
id, plugin_id, scope_type(global, account), scope_id nullable,
enabled, config json, updated_by, updated_at
UNIQUE(plugin_id, scope_type, scope_id)
```

`audit_logs`：

```text
id, actor_id, action, resource_type, resource_id, account_id,
request_id, metadata(redacted), created_at
```

### 2.11 `conversation_segments`

```text
id, account_id, contact_id, conversation_id,
start_message_id, end_message_id, start_cursor, end_cursor,
analyzer_version, content_hash, status, created_at, updated_at
UNIQUE(conversation_id, start_message_id, end_message_id, analyzer_version, content_hash)
INDEX(account_id, conversation_id, end_cursor DESC)
```

同一消息区间和分析输入只能生成一个 segment；查询和写入必须同时验证 `account_id/contact_id/conversation_id` 一致。

### 2.12 `conversation_summaries`

```text
id, account_id, contact_id, conversation_id, segment_id nullable,
summary_type(segment,daily,weekly,rolling), summary_json,
analyzer_version, input_hash, status(pending,completed,failed,stale,superseded), stale bool,
version, supersedes_summary_id nullable, source_cursor_start, source_cursor_end,
created_at, updated_at
UNIQUE(conversation_id, summary_type, analyzer_version, input_hash)
INDEX(account_id, contact_id, status, updated_at DESC)
```

总结不可原地覆盖；新版本通过 `version` 和 `supersedes_summary_id` 建立版本关系。增量处理以 source cursor 推进；消息编辑/删除将受影响结果标记 `stale`。

### 2.13 `profile_claims`

```text
id, account_id, contact_id, conversation_id nullable,
claim_key, value_json, source_type(explicit_fact,observed_pattern,model_inference,manual),
confidence, status(proposed,accepted,rejected,superseded,expired),
sensitivity(normal,private,restricted), manual_lock bool,
analyzer_version, valid_from, valid_until, version, created_by,
created_at, updated_at
UNIQUE(account_id, contact_id, claim_key, version)
INDEX(account_id, contact_id, status, claim_key, updated_at DESC)
```

`version` 是 optimistic lock version；更新必须比较旧版本，人工锁定后 Worker 只能创建冲突建议，不能覆盖当前值。

### 2.14 `profile_claim_evidence`

```text
id, account_id, contact_id, conversation_id nullable,
claim_id, evidence_type(message,summary,manual_note), evidence_id,
excerpt_hash, created_at
UNIQUE(account_id, claim_id, evidence_type, evidence_id)
INDEX(account_id, contact_id, claim_id)
```

复合唯一键保证 Worker 重试不会重复挂接同一证据。

### 2.15 `profile_snapshots`

```text
id, account_id, contact_id, conversation_id nullable,
version, snapshot_json, is_current bool, source_claim_cursor,
source_claim_versions JSONB(claim_key -> claim_id/version), source_profile_revision, created_at
UNIQUE(account_id, contact_id, version)
UNIQUE(account_id, contact_id) WHERE is_current=true
INDEX(account_id, contact_id, is_current)
```

每联系人只允许一个当前版本；以 `(account_id, contact_id, is_current=true)` 索引实现当前 Snapshot O(1) 读取，历史版本保持不可变。`contacts.profile_revision` 是联系人级单调版本：真正创建 Claim 或 transition 成功时原子递增，同值幂等 upsert 与 rebuild 不递增。Snapshot 发布必须同时 CAS `expected_current_version` 与 expected profile revision，并保存 `source_profile_revision`；`source_claim_versions` 精确记录每个 claim_key 使用的 claim_id/version，历史可重建。restricted Claim 默认排除，private 可进入（未来 API 再做授权）。

P0 阶段所有画像 Repository 写路径在 Repository transaction boundary 强制校验 Contact/Conversation/Message/Summary 的 account/contact/conversation scope；跨 scope 抛 `ScopeViolation`。为避免本阶段高风险重写 0001 老表，数据库 composite foreign key 作为 P1 migration 补齐。

### 2.16 `memory_items`

```text
id, account_id, contact_id, conversation_id nullable,
memory_key, memory_type, value_json, search_text, keywords,
status(active,rejected,expired,deleted), importance, expires_at,
last_verified_at, embedding_ref nullable, source_claim_id nullable,
created_at, updated_at
UNIQUE(account_id, contact_id, memory_key)
INDEX(account_id, contact_id, status, updated_at DESC)
INDEX(account_id, contact_id, status, expires_at)
```

结构化过滤和关键词检索使用普通列；`embedding_ref` 可指向 pgvector 记录，但向量能力关闭时契约仍可运行。

### 2.17 `analysis_jobs`

```text
id, account_id, contact_id nullable, conversation_id nullable,
parent_job_id nullable, job_type,
status(pending,claimed,running,retry,completed,failed,dead,cancelled),
priority, available_at, lease_owner nullable, lease_expires_at nullable,
attempts, max_attempts, idempotency_key, input_hash,
progress_total, progress_completed, progress_failed,
budget_tokens, budget_cost, created_at, updated_at
UNIQUE(account_id, idempotency_key)
INDEX(account_id, status, priority DESC, available_at, created_at)
INDEX(parent_job_id, status)
INDEX(status, lease_expires_at)
```

队列并发规则：

- PostgreSQL claim 使用 short transaction（短事务）：`SELECT ... FOR UPDATE SKIP LOCKED`，更新为 `claimed` 并提交；AI call 不得占用 DB transaction；
- Worker 完成外部调用后开启新短事务，以 `id + lease_owner + input_hash + version/status` 做 CAS（compare-and-swap）结果提交；lease 丢失或输入变化时拒绝旧结果；
- 批量任务由 parent job 拆为逐联系人 child job，父任务只聚合进度；暂停/取消向未运行子任务传播；
- 调度器必须执行 backpressure，限制队列深度、每 tenant/租户并发、每 account/账号并发和 token/费用 budget；超预算任务延后而非无限 claim；
- retry 采用退避和 `available_at`，超过 `max_attempts` 进入 `dead`；取消使用 `cancelled`，不得复用完成状态。

## 3. 状态机

### 3.1 账号状态

```text
new → qr_pending → connecting → online
online → offline → connecting → online
offline/connecting → error
任意已登录状态 → logged_out
```

`logged_out` 只有显式重新登录才可进入 `qr_pending`。

### 3.2 出站消息状态

```text
queued → sending → sent → delivered → read
queued/sending → failed
failed → queued（显式或策略允许的重试）
```

禁止：

- `failed → sent` 不经过新发送尝试；
- `read → sent` 回退；
- Bridge HTTP 2xx 但无真实 WhatsApp message ID 时直接标记 `sent`。

### 3.3 群发任务

```text
draft → queued → running → completed
running ↔ paused
queued/running/paused → cancelled
running → failed（系统级失败）
```

单个 recipient 失败不自动让整个 job 失败；整体结果可为 completed with failures。

## 4. 旧数据迁移映射

```text
Hermes profile                         → legacy whatsapp_account
sessions.user_id/source                → contact + conversation
messages.id/session_id/role/content    → message
user-aliases / contact_profiles        → contact remark/metadata
user-memory-md + sidecar               → structured profile/notes
web-settings.reply.user_overrides      → contact_ai_overrides
```

导入必须输出：

- 读取记录数；
- 写入记录数；
- 跳过和冲突记录数；
- account 映射；
- 错误列表；
- 导入批次 ID 和校验摘要。
