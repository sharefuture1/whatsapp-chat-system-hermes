# WhatsApp 独立化与多账号架构实施计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将现有 WhatsApp 客服工作台从 Hermes profile/gateway/state.db 完全解耦，直接接入问鼎 AI OpenAI-compatible API，并稳定支持多个 WhatsApp 账号、统一会话、账号路由、任务队列和可观测性。

**Architecture:** 采用“FastAPI 控制面 + 独立 WhatsApp Bridge Worker + PostgreSQL/SQLite 业务库 + 后台任务 Worker + React 管理台”。每个 WhatsApp 账号拥有独立 Baileys socket 与独立凭据目录，但共享标准化事件总线与业务数据库；AI 调用统一经过 `AIProvider`，默认连接 `https://wendingai.future1.us/v1`，默认模型 `gpt-5.3-codex-spark`。迁移期间保留只读导入器读取旧 Hermes `state.db`，正式运行链路不依赖 `hermes` CLI、Hermes profile 或 Hermes gateway。

**Tech Stack:** Python 3.11+、FastAPI、SQLAlchemy 2/Alembic、PostgreSQL（生产）/SQLite（开发）、Node.js + Baileys、Redis + ARQ/RQ（任务队列）、React/Vite、OpenAI-compatible HTTP API、SSE/WebSocket。

---

## 一、目标架构

```text
React/Vite 管理台
        │ REST + SSE/WebSocket
        ▼
FastAPI Control Plane :8792
 ├─ Auth / RBAC
 ├─ Account Service
 ├─ Conversation / Contact Service
 ├─ Message Service / Outbox
 ├─ AI Orchestrator ───────► https://wendingai.future1.us/v1
 ├─ Plugin / Scheduler / Broadcast Service
 └─ Event Stream
        │
        ├──────── PostgreSQL（业务真源）
        ├──────── Redis（队列、锁、在线状态、限流）
        │
        ▼
WhatsApp Bridge Manager :3000
 ├─ account-a Baileys socket ── sessions/account-a/
 ├─ account-b Baileys socket ── sessions/account-b/
 └─ account-n Baileys socket ── sessions/account-n/
        │
        └─ webhook/event push ─► FastAPI /internal/events/whatsapp
```

### 关键边界

1. **FastAPI 是业务真源**：联系人、会话、消息、AI 设置、插件、定时任务、群发任务均落业务数据库。
2. **Bridge 只负责 WhatsApp 协议**：登录、二维码、连接、收消息、发消息、媒体、回执、typing，不保存业务状态。
3. **每条数据带 `account_id`**：多账号下联系人 ID 不能只用 WhatsApp JID；全局键必须是 `(account_id, remote_jid)`。
4. **发送采用 Outbox**：HTTP 返回“已入队”，Worker 发送后再更新 `sent/failed/delivered/read`，绝不把“请求成功”当“消息成功”。
5. **AI Provider 独立**：业务层不能直接散落 `requests.post()`；所有 AI/翻译/总结调用统一经过 provider，便于超时、重试、模型审计和限流。

---

## 二、最终数据模型

### `whatsapp_accounts`

- `id`: UUID/slug，内部账号 ID
- `name`: 展示名
- `phone_number`: 登录后回填
- `status`: `new/qr_pending/connecting/online/offline/error/logged_out`
- `session_path`: 独立凭据目录
- `is_primary`
- `auto_reply_enabled`
- `ai_profile_id`
- `created_at/updated_at/last_seen_at`
- `last_error`

### `contacts`

- `id`
- `account_id`
- `remote_jid`
- `phone_number/lid`
- `display_name/remark/notes/avatar_url`
- `tags/language/metadata`
- 唯一约束：`(account_id, remote_jid)`

### `conversations`

- `id`
- `account_id`
- `contact_id`
- `remote_jid`
- `type`: `dm/group`
- `last_message_at/last_message_preview`
- `unread_count`
- `pinned/muted/archived/deleted`
- `assigned_operator_id`
- `ai_mode`: `off/suggest/auto`
- 唯一约束：`(account_id, remote_jid)`

### `messages`

- `id`: 服务端 UUID
- `account_id/conversation_id/contact_id`
- `wa_message_id`: WhatsApp 原始 ID
- `direction`: `inbound/outbound`
- `sender_jid`
- `type`: `text/image/audio/video/document/system`
- `content/media_url/quoted_message_id`
- `status`: `queued/sending/sent/delivered/read/failed`
- `error_code/error_message/retry_count`
- `created_at/sent_at/delivered_at/read_at`
- 唯一约束：`(account_id, wa_message_id)`，保证 webhook 幂等

### `ai_profiles`

- `id/name`
- `provider`: `wendingai`
- `base_url`: 默认 `https://wendingai.future1.us/v1`
- `default_model`: 默认 `gpt-5.3-codex-spark`
- `temperature/system_prompt/reply_style`
- `timeout_seconds/max_retries`
- `enabled`

API key 不进数据库明文；首版从环境变量读取，后续可使用 KMS/Secret Manager。

### `contact_ai_overrides`

- `account_id/contact_id`
- `model/system_prompt/reply_style/language`
- `auto_reply_enabled`

### 任务表

- `outbox_messages`: 单发可靠队列、幂等键、重试时间
- `broadcast_jobs` + `broadcast_recipients`: 群发进度、逐目标结果、取消、限速
- `scheduled_messages`: 定时任务真实 worker 执行
- `plugin_states`: 可按全局或账号作用域启停
- `audit_logs`: 登录、账号上下线、设置变更、发信、AI 调用审计

---

## 三、AI 接入规范

### 环境变量

```env
WENDING_AI_BASE_URL=https://wendingai.future1.us/v1
WENDING_AI_API_KEY=<server-secret>
WENDING_AI_DEFAULT_MODEL=gpt-5.3-codex-spark
WENDING_AI_TIMEOUT_SECONDS=90
WENDING_AI_MAX_RETRIES=2
```

### 模型优先级

```text
联系人 override
  > WhatsApp 账号 AI Profile
  > 全局默认 gpt-5.3-codex-spark
```

禁止前端直接决定真实 fallback；`GET /api/settings` 返回 `effective_model`、来源层级和 `base_url` 的安全展示值。

### Provider 接口

创建 `src/whatsapp_chat_system/ai/provider.py`：

```python
class AIProvider(Protocol):
    async def chat(self, *, model: str, messages: list[dict], response_format=None) -> AIResult: ...

class WendingAIProvider:
    # POST {base_url}/chat/completions
    # Authorization: Bearer <key>
    # 连接池、超时、有限重试、结构化错误、usage/latency 记录
```

AI 调用记录：`request_id/model/account_id/contact_id/latency/status/token_usage/error`；API key 永不返回前端、永不写日志。

---

## 四、多 WhatsApp 账号设计

### Bridge V2

将现有单 socket `bridge.js` 改为账户管理器：

```text
bridge/
  package.json
  src/server.js
  src/account-manager.js
  src/account-session.js
  src/event-sink.js
  src/normalizers.js
  sessions/<account_id>/
```

`Map<accountId, AccountSession>` 管理多个 `sock`，不再使用全局单例 `sock/messageQueue/connectionState`。

### Bridge 内部 API

- `POST /accounts`：创建账号运行实例
- `POST /accounts/{id}/connect`：启动并产生二维码
- `GET /accounts/{id}/status`
- `GET /accounts/{id}/qr`：返回短期二维码内容/PNG
- `POST /accounts/{id}/logout`
- `DELETE /accounts/{id}`：停止实例；凭据删除必须二次确认
- `POST /accounts/{id}/send`
- `POST /accounts/{id}/send-media`
- `POST /accounts/{id}/typing`
- `GET /health`

Bridge 与 FastAPI 之间使用 `X-Internal-Token`，只绑定 `127.0.0.1` 或 Unix socket。

### 事件推送

Bridge 不再依赖会丢消息的内存 `GET /messages` + `splice()` 队列。改为 webhook 推送：

```json
{
  "event_id": "accountId:waMessageId:eventType",
  "type": "message.upsert",
  "account_id": "sales-laos",
  "occurred_at": 1783..., 
  "payload": { ...标准化消息... }
}
```

FastAPI 用 `event_id` 幂等入库；推送失败进入 Bridge 本地持久化 spool，指数退避重试。第二阶段可换 Redis Streams/NATS，但首版无需过度设计。

### 账号路由

所有前端/API 操作显式携带 `account_id`：

- 会话列表：`GET /api/conversations?account_id=...`
- 联系人：`GET /api/accounts/{account_id}/contacts`
- 发消息：`POST /api/conversations/{conversation_id}/messages`
- 群发：必须指定一个 sender account
- 定时任务：保存 `account_id`

UI 顶部放账号切换器：全部账号 / 单账号；列表显示账号徽标。发送时锁定当前会话所属账号，不能从另一个账号误发。

---

## 五、Hermes 解耦清单

当前真实耦合已确认：

- `config.py` 从 `/root/.hermes/profiles/.../config.yaml`、`state.db`、JSON sidecar 读取配置和状态。
- `messaging.py` 调用 `hermes --profile ... send`，Bridge 失败时回退 Hermes CLI。
- 生产 Bridge 位于 `/usr/local/lib/hermes-agent/scripts/whatsapp-bridge/bridge.js`，由 Hermes gateway 启动。
- `web_api.py` 的 workspace/account UI 仍生成 `hermes -p <profile> whatsapp` 命令。
- 当前 `workspace_id` 实际取 `source=whatsapp`，无法区分多个 WhatsApp 账号。
- 当前消息库无 `account_id`，不同账号相同 JID 会碰撞。

最终应删除运行时依赖：

- `HERMES_HOME`、`DEFAULT_PROFILE`
- `--profile` CLI 参数
- `hermes send` subprocess fallback
- `/root/.hermes/profiles/*` 业务配置
- Hermes `state.db` 作为实时数据源
- Hermes gateway 作为 Bridge 守护者

保留：`legacy/hermes_importer.py`，只用于一次性迁移历史消息/联系人/设置，导入完成后不参与运行。

---

## 六、分阶段实施

### Phase 0：冻结架构和回归基线

**Objective:** 保证迁移期间现网可回滚。

**Files:**
- Create: `docs/plans/2026-07-10-standalone-wendingai-multi-account.md`
- Create: `docs/standalone-migration-checklist.md`

**Steps:**
1. 记录当前 50 个 Python 测试、4 个前端同步测试、当前生产资源与 API 行为。
2. 导出旧 `state.db` schema 和匿名统计，不复制凭据。
3. 添加 feature flag：`RUNTIME_MODE=legacy|standalone`，默认 legacy，避免一次性切换。
4. Commit: `docs: define standalone whatsapp architecture`。

### Phase 1：独立配置与 AI Provider（P0）

**Objective:** AI 链路不再读取 Hermes config，默认固定到问鼎 AI。

**Files:**
- Create: `src/whatsapp_chat_system/settings.py`
- Create: `src/whatsapp_chat_system/ai/provider.py`
- Create: `src/whatsapp_chat_system/ai/service.py`
- Modify: `src/whatsapp_chat_system/rewriter.py`
- Modify: `src/whatsapp_chat_system/web_api.py`
- Test: `tests/test_ai_provider.py`
- Test: `tests/test_model_resolution.py`

**TDD:**
1. 测试默认 base URL/model。
2. 测试联系人 > 账号 > 全局的模型优先级。
3. 测试 401/429/5xx/timeout 映射和有限重试。
4. 测试 API key 不出现在设置接口和日志。
5. 用 mock server 验证真实请求路径为 `/v1/chat/completions`。

### Phase 2：新业务数据库（P0）

**Objective:** 建立独立业务真源和账号维度。

**Files:**
- Create: `src/whatsapp_chat_system/db/base.py`
- Create: `src/whatsapp_chat_system/db/models/*.py`
- Create: `src/whatsapp_chat_system/repositories/*.py`
- Create: `alembic.ini`, `migrations/*`
- Test: `tests/test_account_scoping.py`
- Test: `tests/test_message_idempotency.py`

**TDD:**
1. 两账号相同 JID 可并存。
2. 相同账号重复 `wa_message_id` 只入库一次。
3. 会话查询永不跨账号泄漏。
4. 消息状态严格按状态机推进。

### Phase 3：Bridge V2 单账号兼容模式（P0）

**Objective:** 先让独立 Bridge 在一个账号下完成登录、收发，不依赖 Hermes gateway。

**Files:**
- Create: `bridge/package.json`
- Create: `bridge/src/account-session.js`
- Create: `bridge/src/server.js`
- Create: `bridge/tests/*.test.js`
- Create: `deploy/systemd/whatsapp-bridge.service`

**TDD/验证:**
1. mock Baileys 测账号生命周期和状态。
2. QR 只在未登录时可取，过期自动清除。
3. 发信必须返回真实 WhatsApp message ID。
4. incoming event webhook 重试且带幂等 `event_id`。
5. Bridge 重启后从独立 session 目录恢复。

### Phase 4：Bridge V2 多账号（P0）

**Objective:** 同进程托管多个隔离账号。

**TDD/验证:**
1. 两账号并行连接，不共享 socket/queue/credentials。
2. 账号 A 发送不能调用账号 B socket。
3. A 断线重连不影响 B。
4. 单账号登出只清理自己的 session。
5. 账号级并发、速率限制和健康状态可观测。

### Phase 5：Outbox、定时任务和群发 Worker（P0/P1）

**Objective:** 把目前“只保存不执行”的定时任务和同步群发变为可靠后台任务。

**Files:**
- Create: `src/whatsapp_chat_system/workers/outbox.py`
- Create: `src/whatsapp_chat_system/workers/scheduler.py`
- Create: `src/whatsapp_chat_system/workers/broadcast.py`
- Create: `deploy/systemd/whatsapp-worker.service`

**规则:**
- 单发幂等键，失败指数退避，有限重试。
- 每账号独立限速器，默认保守发送间隔并支持抖动。
- 群发逐收件人记录结果，可暂停/取消/续跑。
- 定时任务使用数据库 claim/lease，防多 worker 重复执行。

### Phase 6：API V2 与前端账号中心（P1）

**Objective:** 用户可在 UI 中扫码新增、切换、停用多个账号。

**Files:**
- Create: `web/src/components/AccountCenter.jsx`
- Create: `web/src/components/AccountSwitcher.jsx`
- Modify: `web/src/App.jsx`
- Modify: `web/src/api.js`
- Modify: `web/src/components/ChatList.jsx`
- Modify: `web/src/components/SettingsPanel.jsx`

**UX:**
- “平台账号”改为真正的 WhatsApp 账号中心，不再展示 Hermes profile/命令。
- 新增账号 → 命名 → 生成 QR → 实时显示连接状态 → 登录成功。
- 会话列表支持“全部账号”聚合，但发信区明确展示发送账号。
- 每个账号显示在线状态、手机号、最后连接、错误、自动回复模式、AI profile。

### Phase 7：历史迁移与切换（P1）

**Files:**
- Create: `src/whatsapp_chat_system/legacy/hermes_importer.py`
- Create: `tests/test_legacy_importer.py`

**Steps:**
1. 只读导入旧 sessions/messages/aliases/contact profiles。
2. 为旧数据指定 legacy account ID。
3. 生成导入报告：记录数、跳过数、冲突数、校验和。
4. 双写观察期：Bridge 新事件写新库，旧系统只读。
5. UI 切新 API；验证后停止 Hermes gateway，不删除旧 profile。

### Phase 8：生产化（P1）

- systemd：API、Bridge、Worker 三服务，独立重启策略。
- PostgreSQL 备份；session 目录加密备份但禁止进 Git。
- HttpOnly session cookie、RBAC、审计日志、内部 token 轮换。
- Prometheus/结构化日志：账号在线数、event lag、发送成功率、AI latency、429/5xx。
- 健康检查分层：`/health/live`、`/health/ready`、账号健康列表。

---

## 七、验收标准

1. 服务器没有 Hermes gateway/CLI 时，API、前端、AI 改写、WhatsApp 收发仍全部工作。
2. `GET /api/settings` 显示默认 provider 为问鼎 AI、默认模型为 `gpt-5.3-codex-spark`。
3. 真实 AI 请求命中 `https://wendingai.future1.us/v1/chat/completions`；401/429/超时有明确错误且不误报成功。
4. 至少两个 WhatsApp 账号同时在线、同时收消息、分别发消息，数据不串号。
5. 同一个联系人号码在两个账号下生成两个隔离会话。
6. Bridge/API/Worker 任一重启不丢已接收事件和待发任务。
7. 定时任务到点真实发送；群发可看实时进度、失败项和取消状态。
8. 所有插件开关均在后端 API/worker 中有真实 gate；无 hook 的功能不显示为可用。
9. 前端 build、Python tests、Node tests、两账号端到端测试全部通过。
10. 切换后保留旧 Hermes 数据只读备份，可在一个部署窗口内回滚。

---

## 八、推荐执行顺序

不要先大改 UI，也不要直接把当前 `bridge.js` 粗暴复制后立刻停 Hermes。正确顺序：

1. **先做独立配置 + WendingAI provider**。
2. **再做带 `account_id` 的新数据库**。
3. **抽出 Bridge V2，先单账号跑通**。
4. **扩成多账号 + webhook 幂等**。
5. **接 Outbox/定时/群发 worker**。
6. **最后替换前端账号中心和迁移历史数据**。
7. **双写观察通过后才停止 Hermes gateway**。

这样风险最低，也能保证每个阶段都有可运行成果。
