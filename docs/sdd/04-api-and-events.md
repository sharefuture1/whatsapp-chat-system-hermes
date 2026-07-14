# API 与事件契约

## 1. 通用规范

- 外部 API 前缀：`/api/v1`；Legacy `/api/*` 在迁移期保留。
- 内部 Bridge API：`/internal/*` 或独立 loopback 端口。
- JSON 使用 UTF-8 和 snake_case。
- 时间为 ISO 8601 UTC。
- 创建发送/任务类请求支持 `Idempotency-Key`。
- 错误响应统一：

```json
{
  "error": {
    "code": "account_offline",
    "message": "WhatsApp account is offline",
    "retryable": true,
    "request_id": "req_...",
    "details": {}
  }
}
```

- 所有响应附 `X-Request-ID`。
- API key、内部 token 和 WhatsApp credentials 不得返回客户端。

## 2. 鉴权

### 外部 Web

目标：HttpOnly Cookie session + CSRF。迁移期可兼容 `x-session-token`，但新 API 不得新增对 localStorage token 的依赖。

### Bridge 内部认证

```http
X-Internal-Token: <secret>
X-Request-ID: <id>
```

Bridge 仅绑定 `127.0.0.1` 或 Unix socket。

## 3. WhatsApp 账号 API

### `GET /api/v1/accounts`

返回账号及安全状态，不返回 session 路径的真实敏感细节。

### `POST /api/v1/accounts`

```json
{
  "name": "老挝销售号",
  "is_primary": false,
  "ai_profile_id": null,
  "auto_reply_mode": "suggest"
}
```

返回 `201` 和账号对象。

### `PATCH /api/v1/accounts/{account_id}`

用于更新账号业务配置：

```json
{
  "name": "老挝销售号",
  "is_primary": true,
  "enabled": true,
  "ai_profile_id": null,
  "auto_reply_mode": "suggest"
}
```

规则：

- 所有字段可选，未提交字段保持原值；
- `name` trim 后不能为空；
- `is_primary=true` 必须在同一事务中取消旧主账号；
- `enabled=false` 只停用业务账号，默认保留 WhatsApp session 和历史数据；
- 停用在线账号时控制面请求 Bridge 停止该账号 socket，但不得登出 WhatsApp；
- `enabled=true` 不等于 `online`，恢复连接必须显式调用 `connect`；
- 更新必须写审计日志。

### `POST /api/v1/accounts/{account_id}/connect`

触发 Bridge 创建/恢复连接。返回 `202`。

### `GET /api/v1/accounts/{account_id}/qr`

仅 `qr_pending` 时返回：

```json
{
  "account_id": "...",
  "status": "qr_pending",
  "qr_data_url": "data:image/png;base64,...",
  "expires_at": "..."
}
```

二维码过期返回 `410 qr_expired`。同一二维码一旦过期，在收到新 QR 或开始新一轮 `connect` 前，重复读取必须持续返回 `410 qr_expired`；账号状态同时必须满足 `has_qr=false`，不得继续报告 `qr_pending`。

账号生命周期操作按 `account_id` 串行化；`DELETE` 执行期间到达的同账号 `create/connect` 必须等待删除完成后再执行，不得先返回成功再被进行中的删除移除。

### `POST /api/v1/accounts/{account_id}/logout`

登出 WhatsApp，但不自动删除业务数据。

### `DELETE /api/v1/accounts/{account_id}`

必须提交：

```json
{
  "confirm_name": "老挝销售号",
  "delete_session": false
}
```

## 4. 会话、联系人和消息 API

### `GET /api/v1/conversations`

参数：

```text
platform=all|whatsapp|telegram|...
account_id=all|uuid
cursor=<opaque>
limit=50
query=
pinned=
unread=
```

规则：

- `platform=all&account_id=all` 返回所有已接入平台、所有账号的统一时间线；
- 选择平台后返回该平台全部账号；选择账号后再限定到该账号；
- 每条会话必须返回 `platform`、`account_id`、`account_name`、`conversation_id`；
- `available_platforms` 与 `available_accounts` 用于构建 `ALL → WA → WA1/WA2/WA3` 两级筛选；
- 返回 opaque cursor，不允许前端构造数据库 offset 依赖。

### `GET /api/v1/contacts`

参数：`platform=all|...`、`account_id=all|uuid`、`query`、`limit`。每条联系人必须携带平台、账号、远端 ID、展示名/备注及可进入的会话 ID；同一远端 ID 在不同账号下不得合并为一条。显示名固定按 `remark → display_name → conversation.title → remote_jid` 选择，且 `chats.*` 标题更新不得覆盖已经同步的 `Contact.display_name`。已软删除会话不得删除联系人，联系人仍返回且 `conversation_id=null`。

### `DELETE /api/v1/conversations/{conversation_id}`

仅设置会话 `deleted_at` 并从会话列表隐藏；不得删除 Contact、Message 或历史数据。会话与账号 scope 必须保持一致。

### `POST /api/v1/contacts/{contact_id}/conversation`

确保联系人拥有可见会话：存在软删除会话时恢复同一会话，完全不存在时创建空会话；必须使用联系人自身 `account_id + remote_jid`，禁止跨账号复用。

Legacy 迁移接口 `GET /api/contacts` 复用 Legacy 摘要，但不应用 `chat_ops.deleted` 过滤，并返回 `conversation_deleted`；`GET /api/conversations` 保持原删除过滤语义。

### `GET /api/v1/conversations/{conversation_id}/messages`

参数：`before_cursor`、`after_cursor`、`limit`。

返回消息的真实状态、账号 ID 和媒体元数据。

### `POST /api/v1/conversations/{conversation_id}/messages`

Header：

```http
Idempotency-Key: <client-generated-uuid>
```

Body：

```json
{
  "type": "text",
  "content": "你好",
  "quoted_message_id": null
}
```

返回 `202`：

```json
{
  "message": {
    "id": "...",
    "account_id": "...",
    "status": "queued"
  }
}
```

### `POST /api/v1/messages/{message_id}/retry`

只允许 `failed` 且错误可重试的消息；生成新的 outbox attempt，但保持业务消息关联。

### `GET/PUT /api/v1/contacts/{contact_id}`

支持备注、标签、语言、notes；必须校验当前用户能访问该 contact 的 account。

## 5. AI API

### `POST /api/v1/ai/reply-preview`

```json
{
  "conversation_id": "...",
  "source_text": "请帮我回复",
  "mode": "smart"
}
```

返回：

```json
{
  "suggestion": "...",
  "language": "Lao",
  "model": "gpt-5.3-codex-spark",
  "model_source": "global_default",
  "provider": "wendingai",
  "request_id": "...",
  "used_fallback": false
}
```

### `POST /api/v1/messages/{message_id}/translate`

异步情况下返回 `202 task_id`；已有缓存可返回 `200`。

### `GET /api/v1/ai/settings`

返回：

```json
{
  "provider": "wendingai",
  "base_url": "https://wendingai.future1.us/v1",
  "default_model": "gpt-5.3-codex-spark",
  "effective_model": "gpt-5.3-codex-spark",
  "model_source": "database_override",
  "api_key_configured": true,
  "api_key_hint": "••••a9K2"
}
```

不得返回 API key 或密文。

### `PUT /api/v1/ai/settings`

```json
{
  "default_model": "gpt-5.4",
  "api_key": "new-secret-or-empty-to-keep"
}
```

规则：

- 仅管理员可调用；
- `default_model` trim 后为空则恢复 `gpt-5.3-codex-spark`；
- `api_key` 为空或省略表示保留当前密钥；
- 新密钥必须使用 `AI_SECRET_ENCRYPTION_KEY` 做认证加密后入库；
- 响应只返回安全字段，并在保存后立即成为后续 AI 请求的有效配置；
- 更新必须写审计日志，但审计内容不得包含明文 key。

### `DELETE /api/v1/ai/settings/api-key`

必须提交二次确认字段；清除数据库密钥后回退环境变量。若环境变量也为空，则 `api_key_configured=false`，AI 请求返回结构化 `configuration_error`。

## 6. 插件 API

### AI 关系智能 P0 API

- `POST /api/v1/conversations/{conversation_id}/summary-jobs`
- `POST /api/v1/contacts/{contact_id}/profile-jobs`
- `POST /api/v1/profile-jobs/bulk`
- `GET /api/v1/analysis-jobs/{job_id}`
- `GET /api/v1/contacts/{contact_id}/claims?cursor=<opaque>&limit=50`
- `GET /api/v1/contacts/{contact_id}/memories?cursor=<opaque>&limit=50`
- `GET /api/v1/contacts/{contact_id}/summaries?cursor=<opaque>&limit=50`
- `PATCH /api/v1/contacts/{contact_id}/claims/{claim_id}`

触发分析的 POST 必须携带 `Idempotency-Key`，只入队，不同步调用 AI；统一返回 `202` 和 `{ "job_id": "...", "status": "pending" }`。请求必须校验路径资源与 body 中 `account_id/contact_id/conversation_id` scope 一致，禁止跨账号任务。

所有列表使用 opaque keyset cursor；cursor 编码稳定排序键与 scope，禁止 offset/页码分页（offset forbidden）。

Claim PATCH 必须携带 `If-Match: <version>`，服务端以 optimistic version/CAS 更新；版本不匹配、manual lock 冲突或 Worker 提交旧结果均返回 `409 claim_version_conflict`，成功响应返回递增后的 `version`。

批量画像 API 创建 parent `job_id`，由 Worker 拆分 child jobs；配置包含范围、dry-run、empty/stale、账号/租户并发与预算。读取任务返回 progress total/completed/failed；暂停、取消和失败重试均操作任务状态，不在 API 请求事务内调用 AI。

### `GET /api/v1/plugins`

每个插件必须返回：

```json
{
  "id": "auto_translate",
  "available": true,
  "enabled": true,
  "scope": "account",
  "hooks": ["message.ingested", "translation.worker"],
  "not_available_reason": null
}
```

`hooks=[]` 时 `available` 必须为 false。

## 7. 受控 AI 人设 API

所有受控人设仅由服务端代码内置，禁止远程下载/执行；UI 不展示任何外部源/仓库信息。

### `GET /api/v1/personas`

返回当前可分配的受控人设元数据与各会话分配状态。响应结构：

```json
{
  "items": [
    {
      "id": "tong-jincheng",
      "name": "直球关系顾问",
      "description": "以坦诚、清晰和尊重边界的方式提供关系沟通建议。",
      "category": "relationship",
      "accent": "坦诚直接、尊重边界",
      "available": true
    }
  ],
  "contact_assignments": {
    "<contact_id>": "tong-jincheng"
  },
  "plugin_enabled": true
}
```

- `available=true` 表示人设元数据完整且 prompt 可用；不存在的人设不出现在 `items`。
- 真实 `prompt` 永不返回给客户端；UI 只展示 `name/description/accent`。
- `default` 人设不返回；它代表"未选人设"的回退。

### `PUT /api/v1/personas/{persona_id}/enable`

请求体：

```json
{ "enabled": true }
```

- 写入 `web_settings.plugins.persona_styles`；返回当前状态 `{ "id": "...", "enabled": true }`。
- `persona_id` 必须是已知受控人设，否则 `404 persona_not_found`。
- `persona_id="default"` 不可启用/禁用（人设插件开关仅作用于 default 以外的其他人设），否则 `400 persona_default_immutable`。
- 关闭后人设插件视为不可用，UI 与重写器均回退默认策略。

### `PUT /api/v1/contacts/{contact_id}/persona`

请求体：

```json
{ "persona_id": "tong-jincheng" }
```

- 写入 `web_settings.contact_profiles[contact_id].persona_id`。
- 同 `(contact_id, persona_id)` 重复写入幂等返回 200。
- `persona_id` 必须是受控人设或 `"default"`；否则 404 `persona_not_found`。
- 清空选择可发送 `{ "persona_id": "default" }`，也允许 `null` 表示清除。
- 校验由 `web_settings.contact_profiles` 的现有 schema 完成；服务必须拒绝非法 JSON。

### `PUT /api/v1/plugins/{plugin_id}`

```json
{
  "scope": "account",
  "scope_id": "account-uuid",
  "enabled": false,
  "config": {}
}
```

## 7. 定时、群发与 Outbox API

Standalone V1 当前接口：

| 方法 | 路径 | 语义 |
|---|---|---|
| `GET` | `/api/v1/schedule` | 列出 `schedule:` Outbox 任务及状态 |
| `POST` | `/api/v1/schedule` | 未来 UTC 时间入队，返回 `202` |
| `DELETE` | `/api/v1/schedule/{outbox_id}` | 取消尚未完成的定时任务 |
| `GET` | `/api/v1/broadcast` | 按 batch 聚合目标及逐项状态 |
| `POST` | `/api/v1/broadcast` | 每个有效目标独立入队，返回 `202` 与 queued/rejected 明细 |
| `GET` | `/api/v1/outbox` | 仅诊断用途的最近 Outbox 状态 |

所有写操作的投递语义：

- 业务消息和 Outbox 在同一事务创建；API 返回 `queued`，不得提前返回 `sent`；
- 请求可携带 `idempotency_key`；同 key 必须返回同一逻辑消息，不重复调用 Bridge；
- Dispatcher 只可由当前 lease owner 完成/失败；Bridge 成功必须携带真实 WhatsApp `message_id`；
- 迁移期 Legacy `/api/schedule` 与 `/api/broadcast` 保持 503，客户端必须按 runtime mode 选择 V1 接口。

P1 扩展（尚未完成）：`broadcast_jobs`、暂停/续跑、账号限速/抖动、大批量 keyset recipients API。

## 8. Bridge V2 API

- `POST /accounts`
- `POST /accounts/{id}/connect`
- `GET /accounts/{id}/status`
- `GET /accounts/{id}/qr`
- `POST /accounts/{id}/logout`
- `POST /accounts/{id}/stop`
- `DELETE /accounts/{id}`
- `POST /accounts/{id}/send`
- `POST /accounts/{id}/send-media`
- `POST /accounts/{id}/typing`
- `GET /health/live`
- `GET /health/ready`

发送成功必须返回：

```json
{
  "success": true,
  "account_id": "...",
  "chat_id": "...",
  "message_id": "real-whatsapp-id"
}
```

没有 `message_id` 不得认为成功。

`POST /accounts/{id}/stop` 只关闭当前账号 socket、取消重连并保留 session 凭据，账号可在之后显式 reconnect；不得等同于 WhatsApp logout，也不得退出 Node 主进程。

`POST /accounts/{id}/send-media` 本阶段只接受受控媒体引用，不接受任意绝对路径：

```json
{
  "chat_id": "...",
  "media_type": "image",
  "media_ref": "account-scoped-media-id",
  "caption": null,
  "file_name": null,
  "mime_type": null
}
```

Bridge 必须校验 `media_ref` 最终路径位于当前账号媒体根目录内。

## 9. Bridge → FastAPI 事件

Endpoint：

```text
POST /internal/events/whatsapp
```

Envelope：

```json
{
  "event_id": "occurrence-unique-event-id",
  "event_type": "message.upsert",
  "account_id": "...",
  "occurred_at": "2026-07-10T00:00:00Z",
  "sequence": 42,
  "payload": {}
}
```

Envelope 规则：

- `event_id` 在 `account_id` 范围内标识一次事件 occurrence：每次新的 Baileys 回调必须生成新唯一 ID，即使类型和内容完全相同；同一已落盘 FileSpool envelope 的重放保留原 `event_id` 与 `sequence`；数据库唯一键为 `(account_id, event_id)`；
- `sequence` 是每个账号连接事件流的单调整数，状态事件不得被较小 sequence 回退；
- Receiver 保存 canonical payload hash；相同 `(account_id,event_id)` 但 payload/hash 不同返回 `409 event_identity_conflict`；
- 已 `processed` 的重复事件返回 200/duplicate=true；首次失败若事务回滚则允许同一 event 重试；
- Bridge 必须先将事件原子写入本地 spool，再发 webhook；timeout、网络错误、401/403、409、5xx 均不得删除 spool；422 schema error 移入 dead-letter。

`message.upsert` payload v1：

```json
{
  "schema_version": 1,
  "wa_message_id": "ABC123",
  "remote_jid": "85620...@s.whatsapp.net",
  "sender_jid": "85620...@s.whatsapp.net",
  "participant_jid": null,
  "from_me": false,
  "conversation_type": "dm",
  "message_type": "text",
  "timestamp": "2026-07-10T00:00:00Z",
  "text": "hello",
  "push_name": "Customer",
  "quoted_wa_message_id": null,
  "media": null
}
```

核心字段禁止静默忽略未知值；A 账号 envelope 只能写 A 账号联系人、会话和消息。

消息回执状态只允许单调推进 `sent < delivered < read`；迟到回执不得回退，`failed` 不得覆盖已确认的 sent/delivered/read。

事件类型：

- `account.qr`
- `account.connecting`
- `account.connected`
- `account.disconnected`
- `account.logged_out`
- `account.error`
- `message.upsert`
- `message.sent`
- `message.delivered`
- `message.read`
- `message.failed`

FastAPI 返回：

```json
{
  "accepted": true,
  "duplicate": false,
  "event_id": "..."
}
```

重复事件返回 200 且 `duplicate=true`，不得返回错误导致 Bridge 无限重试。

## 10. 前端实时事件

SSE/WebSocket 至少支持：

- `account.status_changed`
- `account.qr_changed`
- `conversation.updated`
- `message.created`
- `message.status_changed`
- `broadcast.progress`
- `scheduled_message.status_changed`
- `plugin.state_changed`

每个事件包含 `event_id`、`account_id`、`resource_id` 和 `occurred_at`。
