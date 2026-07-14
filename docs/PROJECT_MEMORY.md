# PROJECT_MEMORY.md — 项目状态快照

> 最后更新：2026-07-13 UTC

## 当前结论

- 受控 AI 人设 P0（SDD-P0-08 / FR-PLG-007/008 / FR-AI-012）已进入 **Implemented**：V1 API `GET/PUT /api/v1/personas`、`PUT /api/v1/contacts/{contact_id}/persona`；前端 `DiscoverPage` AI 人设分类与 `ChatPane` picker 已接 V1；聊天页头部 `…` 菜单切换人设、预览条同步显示；受控目录仅含 `default / tong-jincheng / professional-service / mature-uncle`，prompt 不下发到客户端，UI 严禁显示任何外部源/仓库信息。
- 人设切换/卸载/未知/插件关闭任一情况，重写器立即回退默认策略；router 与 admin_router 都读 `contact_profiles[contact_id].persona_id`。Legacy V1 注册与鉴权已由回归测试固定；前端人设目录统一走携带 session token 的 API 客户端，不会再将 401 静默伪装成空目录。“童锦程·直球关系顾问”是审计后的通用关系沟通风格；智能/翻译输入工具面板的预览只执行 `preview_only`，不发送消息，且响应展示当前安全人设元数据。
- PC 端 `.wx-sidebar-nav` 桌面 768px+ 真正可见（补齐 `display:flex`），宽度 72px，按钮 52×56，深色模式一致。

- Standalone API 运行时已进入 **Implemented**：`serve` 使用独立 `standalone_api.py`，不加载 Hermes profile/state.db/Legacy Web API；独立 runtime 目录、独立数据库和 Bridge internal token 缺失即拒绝启动。业务库必须处于当前 Alembic head 才 ready。
- standalone 认证仅首启需要至少 12 字符 bootstrap password；已持久化的认证记录可无 bootstrap secret 重启。运行态 JSON 为 0700/0600 原子持久化，配置损坏/认证记录无效会 fail-closed。
- 这是代码与测试层实现，不是已切流结论：生产仍有 Legacy 服务/数据面，独立 Bridge、历史迁移、前端 V1 单源和真实 WhatsApp 收发验收仍待完成。

- Standalone 可靠性分支已合并到 main（代码/测试层）：`OutboxDispatcher` 在 Standalone lifespan 中运行，业务消息/Outbox 原子入队，lease owner、Bridge idempotency key、receipt 持久化恢复、retry/dead 状态均有回归。Standalone V1 有 `/api/v1/schedule`、`/api/v1/broadcast`、`/api/v1/outbox`，写入为 202 queued；Legacy API 继续保持 503 直至生产切流。群发尚缺限速、暂停/续跑和独立 job/recipient 模型；真实 WhatsApp Outbox 收发和多 Worker 验收尚未完成。
- 插件目录（发现页与 Settings→Tools）现显示操作状态、不可用 Worker 原因、busy/error/empty/refresh 状态，并禁用不可用开关和隐藏不真实的删除动作。
- 中文 locale 已由静态覆盖测试守护：首次访问/未知语言/缺失 key 默认回退中文，中文界面不允许残留未翻译英文（WhatsApp、Hermes、AI、API 等协议/产品专有名词除外）。联系人显示名为“人工备注 → WhatsApp 同步 display_name/push_name → 会话标题 → 远端 ID”，同步名称不得被低优先级聊天标题覆盖。
- AnalysisJobRepository 的生产语义未改；其测试固定时间已显式传递 `available_at=now`，消除实际日期推进造成的 false negative。

- Bridge 同步事件身份已按 Baileys occurrence 修复：每次新回调生成唯一 nonce，同内容跨 occurrence 不再复用 `event_id`；FileSpool 重放仍原样保留已落盘 `event_id + sequence`。

- 会话与通讯录生命周期已分离：Legacy `/api/contacts` 保留隐藏会话联系人；Standalone 会话删除仅软删除，联系人和历史不删；通讯录点击可恢复/确保会话后进入聊天。
- AI 自动回复/翻译网页同步已修复：Legacy delta 同会话改为 single-flight/coalesced，不再由新 tick 废弃慢响应；相同消息 ID 改为 upsert 并精确统计新消息；V2 无有效翻译元数据时保留本地译文；翻译失败 30 秒有界重试。
- Legacy delta GET 现在只读取已有翻译缓存，不在轮询请求内调用 AI Provider；旁路 JSON 缓存仍为 O(用户翻译历史)，后续应迁移数据库 revision/event cursor 或 SSE/WebSocket `translation.completed`。
- AnalysisJobRepository 已进入 **Implemented**：aware PostgreSQL 时间、有界 claim、account/input/lease CAS、parent row lock/cancel、recovery `SKIP LOCKED`、全局/账号 P0 backpressure 和 committed `JobLease` 短事务入口已落地；AI focused 五套 50 passed，真实 Worker loop 尚未接线。

- AI 关系智能 P0 数据层已进入 **Implemented**：Alembic `0004`、7 个核心实体和并发安全 `ProfileRepository` 已落地；Summary/Profile Worker、API 和前端尚未接线，因此未标记 Verified。
- 画像写路径强制 account/contact/conversation scope；Claim + Evidence + `profile_revision`、Claim transition 和 Snapshot 发布均在 savepoint 内原子执行，CAS 冲突后 Session 可安全恢复。
- Snapshot 保存精确 Claim ID/版本集合和联系人级 revision；人工锁定优先、Worker 不得覆盖、restricted/过期信息不进入默认 Snapshot。
- 多平台接入方向已确定：Telegram 客服优先 Business Connected Bots，Meta 只走 Page/Instagram Professional/WhatsApp Cloud 官方 Business API；个人 Facebook Inbox 与非官方浏览器自动化明确排除。

- 前端性能调度已完成一轮收敛：Workspace 与账号轮询均为 single-flight + completion-scheduled，后台标签不调度常规刷新，恢复可见后只保留一个 loop owner。
- 自动翻译改为单 worker 串行批处理；切换会话或关闭自动翻译会 Abort 旧请求，并用 generation 阻止旧响应写入新会话；失败消息在同批内不重复请求。
- 网页发送成功后已移除 450ms 延迟全量重拉，直接采用服务端真实 ID，并由既有增量轮询完成最终对账。
- 设置页遵循 UX-012/UX-013：桌面为侧栏+独立内容滚动，移动端全屏单行横滑导航、独立内容滚动和固定底部操作栏；主题按钮使用显式 `setTheme`，未知语言 setter 统一回退中文。发现页只保留运营概览与受控 AI 人设，插件目录迁到 Me → 插件中心；定时发送、群发在可靠 Worker 落地前从 UI 移除，API 写入端返回 503。插件中心提供 `/api/plugins` 的真实 `available / unavailable_reason / status_when_on / hooks`，并新增 Scheduler / Broadcast 任务中心。当前生产资源：`index-BSMu_Kn5.js` / `index-BU2zSI7R.css`，本机与公网一致。

- 移动 Chats 已完成微信式两级导航：390×844 初始只显示会话列表，点入聊天后 sidebar/TabBar 隐藏且返回键可见，返回后列表和 TabBar 恢复；桌面 1440×900 保持双栏并隐藏多余底部导航。
- 乐观发送的 `tmp-*`、pending、failed 消息不会进入翻译 API；真实回复 ID 会替换临时 ID，刷新合并按 `role+content` 保留 `sent` 状态。
- 置顶会话只渲染一次；时间固定第一行，未读为第二行纯红点；气泡时间为 HH:MM，同发送方 5 分钟内只在末条显示。
- 输入框按 `scrollHeight` 自动长高并封顶 140px；模式改为直发/智能/翻译三选一；手机设置弹窗全屏。
- 手机浏览器验收：列表 `flex` / 聊天 `none` / TabBar `flex`；进入聊天后列表 `none` / 聊天 `flex` / TabBar `none` / 返回键 `flex`；无横向溢出，长文本高度 140px。

项目**尚未彻底从 Hermes 分离**，但独立 Bridge V2 的代码链路已进入 `Implemented`：

- AI Provider、账号级业务数据库已独立。
- 多账户控制面 API、Bridge HTTP Client、微信式账号中心 UI 已落地。
- 独立 Node/Baileys Bridge V2 已实现账号级 session/socket、QR、状态、重连、发送和回执事件。
- 持久化 FileSpool/EventSink 与 FastAPI `/internal/events/whatsapp` 幂等事务接收已实现。
- 生产仍保留 Legacy `127.0.0.1:3000` 和 Hermes profile/state 兼容链；Bridge V2 `127.0.0.1:3100` 当前真实在线，并已有一个扫码账号将事件写入独立数据库。
- 聊天首页已形成迁移期统一收件箱：`ALL` 聚合 Legacy 与 V2；平台层为 `ALL/WA/...`，平台下为 `WA1/WA2/...`，每条会话使用账号隔离的 `conversation_key`。
- 通讯录已接入独立 `/api/v1/contacts` 并与 Legacy 会话联系人聚合，支持平台/账号筛选、账号分组、搜索和会话跳转。
- 独立库当前实测：`1` 个 V2 业务账号、`2` 个联系人、`2` 个会话、`8` 条消息；Legacy 当前 API 返回 `3` 条会话，统一 ALL 预期显示 `5` 条。
- 真实扫码、第二个 V2 账号隔离、历史迁移、Outbox Worker 与 Hermes shutdown 尚未全部验收。
- V2 当前聊天已按轮询刷新独立消息 API；V2 发送改用当前会话所属账号 Bridge，成功后写独立消息表，不再误走 Legacy `/api/reply`。
- 翻译 API/缓存支持 Legacy 整数和 V2 UUID message ID；“我 → 全局 AI”可配置模型、密钥、提示词、回复风格和自动翻译。
- 当前 V2 业务账号真实状态为 `offline`，所以代码链与运行健康已验证，但新的真实入站/出站/翻译端到端验收仍需账号重新上线。
- 聊天页面闪烁根因已修复：账号 3 秒轮询在数据不变时不再替换数组引用；Workspace 刷新 callback 不再依赖账号数组；ChatPane 初始加载仅依赖稳定会话 identity，不再因 settings 对象刷新而清空消息。
- 微信式聊天页已收敛为单一“…”头部入口、双方 40px 方形头像、左右镜像气泡、译文内嵌气泡和可折叠输入工具面板；移动 390×844 无横向溢出。
- 自动翻译增加 message-id in-flight 去重，同一条消息不会被并行重复请求 Provider。
- 真实 AI 探针已完成老挝语→中文翻译；失败状态会向前端显示配置或 Provider 错误，不再静默或伪装成功。
- 全站页面壳与滚动已完成一轮生产审计：桌面 1440×900 和移动 390×844 无横向溢出，通讯录/发现具有独立滚动容器，React Hooks 顺序崩溃已修复。

## 线上与影子状态

- FastAPI：`http://127.0.0.1:8792`，health 200。
- 前端：`index-DRPbZjTf.js` / `index-n1Ei7oEG.css`，本机 FastAPI 与公网 `https://whats.future1.us` 资源哈希一致。
- Legacy Bridge：`127.0.0.1:3000`，保持运行。
- Bridge V2：`127.0.0.1:3100` 当前运行，live/ready 200，内部 token 与 FastAPI 配置一致；当前登记业务账号状态为 offline。
- 独立会话 API：`/api/v1/conversations` 返回当前 V2 独立库数据，实测全部账号视图 2 条会话。
- 生产仍传入 `/root/.hermes/profiles/whatsapp-support`，属于迁移期兼容。

## 本轮实现：Task 5 + Task 6

### Bridge V2

- 新增 `bridge/` 独立 Node 进程，Baileys 锁定 `6.7.22`。
- AccountManager 按 `account_id` 隔离 session/socket/spool/media。
- 每账号连接互斥、socket generation、指数退避+jitter、stop/logout/delete 语义和生命周期串行化。
- loopback/Host/token/request-id/HTTP timeout/live-ready/优雅关闭安全门禁。
- QR `qr_data_url`、稳定过期语义；定时器或读取触发过期均发送 offline 事件。
- 发送必须获得真实 WhatsApp message ID；回执产生 sent/delivered/read/failed 事件。
- 状态 API 和 account.error 只返回稳定脱敏文案，不暴露路径、token 或底层异常。

### 可靠事件链

- FileSpool 先原子落盘再 POST，账号目录 `0700`。
- pending/inflight/dead、崩溃恢复、指数退避、422 dead-letter、500/timeout/401 保留重试。
- 每账号 sequence 持久化单调；按 sequence/入队顺序 claim。
- 重启自动扫描并 replay spool；同账号只保留一个 EventSink owner。
- 同 event_id 会比较 canonical envelope；不一致显式 identity conflict，不静默吞事件。
- FastAPI 内部事件接口使用常量时间 token 校验、结构化错误和 request ID。
- Receiver 支持 account 状态、message.upsert、sent/delivered/read/failed；按 `(account_id,event_id)` 幂等并校验 payload hash。
- message/contact/conversation/event 同事务落库，状态与回执单调，不跨账号。
- Alembic `0003` 补充 sequence、payload_hash、消息时间字段及旧事件 hash 回填；downgrade 跨账号 event ID 冲突会明确中止。

## 验证状态

```text
pytest -q                          129 passed, 1 warning
bridge npm test                   63 passed
bridge npm run lint               PASS
bridge npm audit --omit=dev       0 vulnerabilities
web node --test tests/*.test.js     35 passed
web npm run build                 PASS
Alembic upgrade→downgrade→upgrade PASS
git diff --check                  PASS
FastAPI /api/health               200
Legacy web reply sync probe       PASS (real WhatsApp ID + local ID + delta API)
V2 shadow live/ready              200
V2 unauth API                     401
V2 create/status/stop             200
```

唯一警告是 FastAPI/Starlette TestClient 上游弃用提醒。

## 下一阶段阻断

1. 用测试 WhatsApp 账号完成真实扫码、session 重启恢复、入站消息、出站真实 message ID 和回执验收。
2. 启动第二账号，完成 A/B 同时在线、断线/登出/删除互不影响验收。
3. 将账号控制面安全配置到 Bridge V2 3100，并保持 Legacy 3000 可回滚。
4. 完成 Outbox Worker 和发送路径切换。
5. 只读导入 Legacy 数据、影子比对、最终停止 Hermes gateway/profile/state 依赖。

## 环境

- 项目：`/home/young11/workspace/whatsapp-chat-system-hermes`
- Python venv：`/home/young11/workspace/whatsapp-chat-system-hermes/.venv`
- GitHub：`https://github.com/sharefuture1/whatsapp-chat-system-hermes`
- 生产端口：`127.0.0.1:8792`

## SDD 开发规范

- 权威入口：`docs/sdd/README.md`。
- 需求/架构/API/优化状态只能在 SDD 中修改。
- 按 requirement ID、计划、RED→GREEN→REFACTOR、双阶段审查、全量门禁、真实部署验证执行。
