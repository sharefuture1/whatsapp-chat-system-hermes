# 系统架构规格

## 1. 目标拓扑

```text
Browser / React Vite
        │ REST + SSE/WebSocket
        ▼
FastAPI Control Plane :8792
 ├─ Auth / RBAC
 ├─ Account Service
 ├─ Contact / Conversation / Message Service
 ├─ AI Orchestrator ─────► Wending AI /v1
 ├─ Plugin Service
 ├─ Schedule / Broadcast Service
 ├─ Audit / Observability
 └─ Internal Event Receiver
        │
        ├─ PostgreSQL（生产真源）
        ├─ Redis（队列、锁、状态、限流）
        │
        ▼
Background Worker
 ├─ Outbox sender
 ├─ Scheduler
 ├─ Broadcast executor
 ├─ AI background tasks
 └─ Retry / dead-letter handling
        │
        ▼
WhatsApp Bridge V2 :3100 (loopback/internal token)
 ├─ AccountSession A ─ sessions/A
 ├─ AccountSession B ─ sessions/B
 └─ AccountSession N ─ sessions/N
        │
        ▼
WhatsApp / Baileys
```

## 2. 组件职责

### 2.1 React 管理台

负责：

- 登录、账号切换、会话与联系人操作；
- 账号 QR 登录和状态展示；
- 消息编辑、预览、发送、失败重试；
- AI、插件、定时、群发配置；
- 实时状态消费和用户反馈。

不得：

- 保存或接触问鼎 AI API key；
- 直接调用 Bridge；
- 自行推断发送成功；
- 只在本地保存业务状态；
- 通过前端隐藏代替后端权限校验。

### 2.2 FastAPI 控制面

负责：

- 外部 API 与鉴权；
- 账号、联系人、会话、消息和设置业务规则；
- Bridge 内部事件验证、标准化和幂等入库；
- 创建 Outbox、定时、群发任务；
- AI Provider 编排和 effective model 解析；
- 向前端推送实时事件；
- 审计和健康检查。

### 2.3 WhatsApp Bridge

负责：

- Baileys socket 生命周期；
- QR、连接、断线、重连、登出；
- 收发文本和媒体；
- typing 与 WhatsApp 回执；
- 将标准化事件可靠推送给 FastAPI；
- 为推送失败事件保留持久化 spool。

不得：

- 处理 AI Prompt；
- 决定联系人业务备注、插件规则或自动回复策略；
- 把内存队列当可靠真源；
- 在账号间共享 socket、session 或消息队列。

### 2.4 Worker

负责：

- claim Outbox 任务；
- 调 Bridge 发送并更新消息状态；
- 执行定时任务；
- 分片、限速、执行和恢复群发；
- 异步翻译、总结、画像更新；
- 重试和 dead-letter。

### 2.5 AI Orchestrator

统一调用：

```text
https://wendingai.future1.us/v1/chat/completions
```

默认：

```text
provider = wendingai
model = gpt-5.3-codex-spark
```

模型解析：

```text
contact_ai_override.model
  ?? account.ai_profile.default_model
  ?? WENDING_AI_DEFAULT_MODEL
```

## 3. Bridge 多账号设计

### 3.1 运行对象

```js
class AccountManager {
  sessions = new Map() // accountId -> AccountSession
}

class AccountSession {
  accountId
  sessionDir
  sock
  connectionState
  qr
  reconnectState
  rateLimiter
  eventSpool
}
```

### 3.2 隔离要求

- session 路径：`runtime/whatsapp/sessions/<account_id>/`；
- spool 路径：`runtime/whatsapp/spool/<account_id>/`；
- 所有 endpoint 必须包含 `account_id`；
- 所有日志必须包含 `account_id`，不得包含完整凭据；
- 单账号异常由该 `AccountSession` 捕获，不使 Node 主进程退出；
- `logged_out` 与临时断线采用不同恢复策略；
- 账号删除和 session 删除是两个独立操作。

## 4. 关键流程

### 4.1 新账号登录

```text
UI 创建账号
→ FastAPI 写 whatsapp_accounts(status=new)
→ FastAPI 调 Bridge POST /accounts
→ Bridge 创建 AccountSession
→ connect 后生成 QR
→ Bridge 推送 account.qr / account.status
→ UI 实时展示 QR
→ 手机扫码
→ Bridge 保存 credentials
→ 推送 account.connected + phone_number
→ FastAPI 更新账号 online
```

### 4.2 入站消息

```text
Baileys messages.upsert
→ Bridge normalize
→ 写入/确认本地 spool
→ POST /internal/events/whatsapp
→ FastAPI 校验 internal token + event_id
→ DB transaction：event + contact + conversation + message
→ 返回 accepted
→ Bridge 从 spool 标记完成
→ SSE/WebSocket 推送前端
→ 可选异步翻译/画像/自动回复任务
```

必须保证重复 webhook 不重复创建消息。

### 4.3 出站消息

```text
UI POST message
→ FastAPI 校验 conversation/account 权限
→ DB 写 outbound message(status=queued) + outbox
→ 返回 202 queued
→ Worker claim outbox
→ status=sending
→ Bridge /accounts/{id}/send
→ 成功：保存 wa_message_id，status=sent
→ 回执：delivered/read
→ 失败：status=failed + error + retry_at
→ 实时通知 UI
```

### 4.4 AI 回复建议

```text
UI 请求 preview
→ FastAPI 加载联系人/会话上下文
→ 解析 effective model
→ WendingAIProvider.chat
→ 校验结构化输出
→ 返回 suggestion + model + source + request_id
→ 用户编辑后发出
```

AI preview 成功不代表消息发送成功。

### 4.5 定时与群发

定时和群发都必须先落数据库，再由 Worker claim。不得在 HTTP handler 中循环同步发送所有联系人。

## 5. 运行模式与迁移

迁移阶段支持：

```env
RUNTIME_MODE=legacy|standalone
```

- `legacy`：当前 Hermes profile/state.db/Bridge 路径，仅用于过渡和回滚；
- `standalone`：独立数据库、Bridge V2、Worker、问鼎 AI Provider；
- 禁止在同一实例中对同一入站事件同时由两个模式自动回复；
- 双写期间必须有 event/message 幂等键。

## 6. 部署单元

生产至少三个服务：

```text
whatsapp-chat-api.service
whatsapp-bridge.service
whatsapp-chat-worker.service
```

数据库和 Redis 可使用托管服务或本机独立服务。API/Bridge/Worker 必须有各自日志、重启策略和健康检查。

### 6.1 Standalone systemd 部署配置合同

`FR-CORE-001`、`FR-CORE-002`、`FR-ACC-003`、`NFR-OPS-001` 的正式 systemd 合同如下；仓库资产是 `deploy/systemd/whatsapp-chat-system.service` 与 `deploy/systemd/whatsapp-bridge-v2.service`。本合同状态为 `Implemented`（仅仓库资产和自动契约测试完成，未做生产安装/真实消息验收），不得标为 `Verified`。

- API 使用 `WorkingDirectory=/opt/whatsapp-chat-system`，以 `/opt/whatsapp-chat-system/.venv/bin/python -m whatsapp_chat_system.cli serve` 启动并只监听 `127.0.0.1:8792`。`ExecStart` 不得包含 `--profile`，不得出现 Hermes 路径或可执行文件。
- API 加载可选的 `EnvironmentFile=-/etc/whatsapp-chat-system/api.env`；`CHAT_SYSTEM_RUNTIME_DIR=/var/lib/whatsapp-chat-system/api` 由 unit 固定为独立目录；`DATABASE_URL` 与 `WHATSAPP_BRIDGE_INTERNAL_TOKEN` 必须由该环境文件或受控 systemd 环境提供。`CHAT_SYSTEM_WEB_DIST` 指向部署目录下的 `web/dist`。环境文件仅由主机受控，禁止提交 token、密码或连接串。
- Bridge V2 使用 `WorkingDirectory=/opt/whatsapp-chat-system/bridge`，以 `/usr/bin/node /opt/whatsapp-chat-system/bridge/src/index.js` 启动，加载可选的 `EnvironmentFile=-/etc/whatsapp-chat-system/bridge.env`。
- Bridge 必须显式设置 `BRIDGE_HOST=127.0.0.1`、`BRIDGE_PORT=3100` 和 `BRIDGE_RUNTIME_ROOT=/var/lib/whatsapp-chat-system/bridge`。其 session、spool、media 均位于此独立 runtime root；`WHATSAPP_BRIDGE_INTERNAL_TOKEN` 从受控环境文件取得并与 API 一致。
- API runtime root 与 Bridge runtime root 必须不同；二者都不得指向 Hermes profile、`state.db` 或任何 Hermes 目录。Bridge 不对公网监听，内部事件只发送至 loopback API。

生产安装、重启、端口探测和 legacy 服务停启不属于本 Task；只能在 MIG-8 的受控切换窗口执行。

### 6.2 前端 Vercel 托管（可选拓扑）

前端 SPA 可迁至 Vercel 托管，后端保持本节 systemd 合同不变；权威规格见 `10-frontend-vercel-deployment.md`（VCL-001~006）。自托管 `CHAT_SYSTEM_WEB_DIST` 模式必须保留为回滚路径。

## 7. 明确不采用

- 每个 WhatsApp 账号启动一整套 FastAPI；
- 继续用 Hermes profile 作为多账号数据隔离；
- Bridge 内存 `GET /messages` + `splice()` 作为可靠事件队列；
- 在 FastAPI 请求线程中同步完成群发；
- 前端直接保存 AI key 或直接调用问鼎 AI；
- 一次性停旧系统并不可逆迁移。
