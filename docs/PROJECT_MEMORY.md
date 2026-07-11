# PROJECT_MEMORY.md — 项目状态快照

> 最后更新：2026-07-11 UTC

## 当前结论

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
- 当前生产资源：`index-CPzFRVjQ.js` / `index-n1Ei7oEG.css`；本机与公网资源一致。Web 39、Python 129、Bridge 63 全部通过；390×844 与 1440×900 公网页均无横向溢出或控制台错误。

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
