# 性能与实时同步规格

> 状态：**Active / Mandatory**
> 基线日期：`2026-07-14`
> 上位需求：`NFR-PERF-001`、`NFR-PERF-002`、`NFR-REL-002`
> 关联 backlog：`SDD-P0-10`（快赢包）、`SDD-P1-12`（SSE 实时通道）、`SDD-P1-05`（翻译异步化）、`SDD-P1-08`（分页与索引）

本文档把 2026-07-14 性能审计的结论固化为强制规格。所有条目在实现时必须先写失败测试，引用本文件的需求 ID。

## 1. 审计结论（问题清单）

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 1 | 前端把刷新间隔强制钳到 ≥30s；设置缺失时完全不轮询 | `web/src/App.jsx`（`Math.max(30, autoSeconds)`） | 新消息延迟 30s+，工作台失去实时性 |
| 2 | 每轮刷新全量拉取 `conversations?limit=200` + `contacts?limit=500` + `dashboard`，且前两个串行 | `web/src/App.jsx` `fetchConversationsPage` | 轮询单次成本高，被迫拉长间隔 |
| 3 | 每轮刷新触发当前会话整页 80 条消息重拉，无增量端点 | `web/src/components/ChatPane.jsx`（`refreshTick` effect） | 带宽/渲染浪费，滚动位置抖动风险 |
| 4 | 翻译端点每请求新建 `Rewriter` → 新建 Provider → 新 `requests.Session` | `api/v1/messages.py` + `rewriter.py` | 每条翻译重做 TLS 握手，连接复用失效 |
| 5 | 翻译结果写旁路 JSON：整读→改→整写，O(历史总量) | `api/v1/messages.py` `_put_translation` | 随使用无限膨胀，阻塞请求线程 |
| 6 | AutoReplyWorker 持有 DB session/事务期间同步调 AI（最长 90s） | `ai/auto_reply_worker.py` `_process` | SQLite 下阻塞全部写入；Postgres 下占用连接 |
| 7 | SQLite 未开 WAL / busy_timeout；worker 1–2s 轮询写与 webhook/API 争锁 | `db/session.py` | database is locked、请求毛刺 |
| 8 | 消息分页按 `COALESCE(occurred_at, created_at)` 排序，无匹配索引 | `api/v1/conversations.py` | 每页请求全排序会话消息 |
| 9 | `mergeFreshMessages` 无变化也返回新数组；localStorage 同步写 300 条 JSON | `web/src/chatSync.js`、`chatCache.js` | 每轮全列表重渲染 + 主线程阻塞 |

## 2. 性能需求

### PERF-001 前端刷新调度合同 [Approved]

- 自动刷新间隔尊重服务端 `ui.auto_refresh_seconds`，允许范围 `[3, 300]` 秒；越界钳到边界，禁止再引入 30s 下限。
- 设置缺失或非法时默认 **5 秒**，禁止解释为"关闭轮询"。
- 保持既有 single-flight、完成后调度、hidden tab 暂停、恢复可见只保留一个 loop owner 的基线（不得回归）。
- SSE 通道（RT-001）建立后，轮询自动降级为 ≥60s 的兜底对账，SSE 断开时恢复主动轮询。
- 验收：静态回归测试断言无 `Math.max(30`；间隔=0/缺失/超界的行为有单测。

### PERF-002 工作台轮询负载合同 [Approved]

- 常规轮询只允许拉：会话列表（`limit` ≤ 实际页大小，默认 50）+ dashboard，二者必须并行。
- 通讯录（contacts）不进入常规轮询；仅在登录初始化、进入通讯录页、手动刷新时拉取。
- 会话列表 API 增加 `updated_since`（ISO 8601）参数：只返回该时间之后有变化的会话；客户端记录服务器返回的 `server_time` 作为下一轮游标。全量拉取仅用于首屏与显式刷新。
- 验收：一轮常规轮询的请求数 ≤ 2；`updated_since` 有后端单测（变更命中/未变更为空）与前端合并单测。

### PERF-003 AI Provider 单例与连接复用 [Approved]

- 进程内 AI 调用（翻译端点、reply-preview、AutoReplyWorker、Rewriter）必须复用 app 级单例 Provider/Session，禁止在请求路径上新建 `Rewriter`/`WendingAIProvider`/`requests.Session`。
- 单例挂载 `app.state`，注入运行时设置管理器以保持"保存后热生效"语义。
- 验收：单测断言两次翻译请求命中同一 Session；现有 `test_provider_default_session_is_persistent_and_reused` 保持通过。

### PERF-004 翻译结果数据库化 [Approved]

- 新增 `message_translations` 表（见 `03-data-model.md` 扩展）：`message_id`(FK)、`source_lang`、`target_lang`、`content`、`provider_model`、`created_at`；同一 `message_id + target_lang` 唯一。
- 消息列表 API 直接内联返回已存在译文；前端不再对已翻译消息发起 POST。
- 旁路 JSON `translations__{user}.json` 冻结为只读迁移源，禁止新增写入；提供一次性迁移脚本。
- 验收：翻译一次后再次拉取消息即带译文；重复翻译请求幂等返回已有译文；JSON 文件在新链路零写入。

### PERF-005 数据库引擎健康合同 [Implemented → 扩展 Approved]

- 已落地：非 SQLite 引擎 `pool_pre_ping=True`、`pool_recycle=1800`、`pool_size=10`、`max_overflow=20`。
- 新增：SQLite 连接必须设置 `PRAGMA journal_mode=WAL` 与 `PRAGMA busy_timeout=5000`（与既有 `foreign_keys=ON` 同一 connect 监听器）。
- 生产 `DATABASE_URL` 必须显式设置（`DEPLOYMENT.md` 既有红线），SQLite 仅限开发。
- 验收：单测断言 SQLite 连接 `journal_mode='wal'`、`busy_timeout=5000`；Postgres kwargs 单测保持通过。

### PERF-006 Worker 事务与外部调用隔离 [Approved]

- 任何 Worker（AutoReply、Outbox、未来画像 Worker）不得在持有数据库 session/事务期间进行外部网络调用（AI Provider、Bridge HTTP）。
- 标准模式：短事务读取上下文并提交关闭 → 无 session 状态下调用外部服务 → 新短事务写回结果（写回前重校验 lease/version）。
- 验收：AutoReplyWorker 单测注入慢 Provider，断言 AI 调用期间无打开的 session/事务；lease 过期后写回被拒绝的既有语义保持。

### PERF-007 消息分页排序与索引对齐 [Approved]

- `occurred_at` 回填为 NOT NULL（缺失取 `created_at`），排序与游标统一使用 `(occurred_at, id)`，删除 `COALESCE` 表达式排序。
- 新增索引 `ix_messages_conversation_occurred_id (conversation_id, occurred_at DESC, id DESC)`；Alembic 迁移含回填与降级。
- 验收：迁移 upgrade/downgrade 测试；分页语义回归（含同秒多条、游标穿越）保持通过。

### PERF-008 前端渲染与本地缓存稳定性 [Approved]

- `mergeFreshMessages` 在服务端数据与本地一致时必须返回原数组引用；有既有引用稳定测试风格可复用。
- `saveConversationCache` 的 localStorage 写入移出关键路径（`requestIdleCallback`，降级 `setTimeout(0)`）。
- 消息气泡子组件 memo 化；`translationQueueVersion` 一类 O(n) 派生值仅在 `messages` 引用变化时重算。
- 切会话时的本地缓存只作为首屏骨架，必须并行发起服务端校验请求，不得以"5 分钟内新鲜"跳过网络请求。
- 验收：静态/单元回归覆盖引用稳定与缓存不短路网络请求。

## 3. 实时同步需求

### RT-001 SSE 事件流端点 [Approved]

- 新增 `GET /api/v1/events/stream`（`text/event-stream`），复用现有 session 鉴权；未认证返回 401。
- 事件类型（首批）：
  - `message.created`：`{conversation_id, message_id, account_id, occurred_at}`
  - `conversation.updated`：`{conversation_id, last_message_preview, last_message_at, unread_count}`
  - `translation.completed`：`{message_id, target_lang}`
  - `account.status`：`{account_id, status}`
- 每条事件带自增 `id:`；支持 `Last-Event-ID` 重连续传（进程内环形缓冲 ≥ 1024 条，超界即指示客户端全量对账）。
- 心跳：每 25s 发送 `: keepalive` 注释行；服务端对单连接设置写超时。
- 事件源为进程内发布器：webhook 落库、Outbox 状态变更、翻译完成处提交事务后发布（严禁事务内发布）。
- 验收：httpx 流式测试覆盖鉴权、心跳、事件推送、Last-Event-ID 续传与超界对账指示。

### RT-002 前端 EventSource 集成与降级 [Approved]

- 前端建立单一 `EventSource`；收到事件做**精确失效**（只刷新受影响的会话/消息/译文），不做全量重拉。
- SSE 连接活跃时常规轮询降为 ≥60s 兜底；`error` 后指数退避重连（1s→2s→…→30s 封顶），期间恢复 PERF-001 主动轮询。
- hidden tab 断开 SSE，可见后重建并做一次对账刷新。
- 验收：既有静态测试风格覆盖"SSE 活跃时无高频轮询定时器""断线恢复轮询"。

### RT-003 与既有基线的关系 [Approved]

- 本章实现即 `SDD-P1-05` 的"SSE/WebSocket 跨客户端实时更新"剩余验收与工程化重构 Phase 2 的正式规格；完成后两处状态同步更新。
- "增量消息严格按 ID 游标""快速切换联系人不串线"等第 5 章基线不得回归。

## 4. 实施顺序与依赖

1. **快赢包 `SDD-P0-10`**（无相互依赖，可一次落地）：PERF-001、002（并行+contacts 拆分部分）、003、005、006、008。
2. **`SDD-P1-12`**：RT-001 → RT-002；PERF-002 的 `updated_since` 可与 SSE 同期或先行。
3. **翻译数据库化 PERF-004** 与 **索引对齐 PERF-007**：各自独立 Alembic 迁移，避免同一迁移混合。

## 5. 质量门禁

- 每个需求 ID 至少一条失败先行的自动化测试；`pytest`、web `node --test`、`vite build`、bridge 测试全绿后才可标记 `Implemented`。
- 生产切流验收（真实 WhatsApp 消息 → SSE 推送 → 页面 3s 内可见）完成后才可标记 `Verified`。
