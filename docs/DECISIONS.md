# DECISIONS.md — 架构决策记录

## 2026-07-11: 同步事件身份按 occurrence 唯一，重放身份由 FileSpool 保留

**决策**：每次新的 Baileys 同步事件回调创建一次 occurrence nonce；批次 `event_id` 由 occurrence nonce、事件类型、chunk index 和 canonical content hash 共同派生。相同内容在不同回调中必须得到不同 ID，同一回调内各 chunk 也必须唯一。

- 只有已经落盘的 FileSpool envelope 重放保留原 `event_id + sequence`。
- 不要求跨独立 Baileys occurrences 的内容稳定 ID；否则相同 ID 配合新 sequence/occurred_at 会触发 canonical envelope identity conflict。
- Receiver 的 `(account_id,event_id)` 幂等与冲突检测保持不变。

**关联规格**：`FR-CON-011`、`API-EVENT`。

## 2026-07-11: 联系人与会话使用独立生命周期

**决策**：删除会话只改变聊天列表可见性，不删除联系人、消息或历史。Legacy 通过独立 `/api/contacts` 暴露被隐藏联系人；Standalone 只设置 `Conversation.deleted_at`，联系人点击通过 ensure/restore 恢复同一会话或创建空会话。

- 联系人身份以 source/account/contact 为边界，会话身份以 `conversation_key` 为前端边界。
- Legacy 删除接口只接受裸 JID；Standalone 删除接口只接受 conversation UUID。
- 恢复必须保留原 conversation ID 和历史；完全无会话时才创建。
- 不修改 Bridge 同步路径。

**关联规格**：`FR-MSG-008`、`FR-CON-001`、`SEC-005`。

## 2026-07-11: AnalysisJob claim 使用 committed wrapper，配额仅作 P0 负载保护

**决策**：外部 AI Worker 只能通过 `claim_next_committed(session_factory, ...)` 获取不可变 `JobLease`，claim 后立即 commit/close；状态转换各自使用新 session 短事务。

- PostgreSQL 依靠行锁 + CAS 硬防重复 claim；SQLite 使用有界候选 + CAS。
- P0 global/account/budget 限制在候选事务内统计；global claim 的 per-account 限制必须进入候选 SQL，以 correlated active count 跳过已满账号，避免高优先级满账号阻塞其他账号。
- parent generation 不新增 child schema 字段：PostgreSQL cancel parent 与 child start/heartbeat/complete/fail 先锁同一 parent row (`FOR UPDATE`) 再 CAS；父已取消/终态禁止新 child enqueue/claim，过期 leased child recovery 直接 cancelled。
- 跨实例全局配额列入 P1，采用 PostgreSQL advisory lock 或 Redis。
- cancel 不保证中断已开始的外部调用，只确保父取消后结果 CAS 被拒绝。

**关联规格**：`DATA-007`、`docs/sdd/03-data-model.md`。

## 2026-07-11: 消息新增游标与翻译字段变更必须分离处理

**决策**：Legacy 新消息继续使用严格 `message_id > after_id` 游标，但同会话请求必须 single-flight/coalesced，不能让后续 tick 废弃当前响应。相同消息 ID 的服务端状态使用 upsert 对账。翻译等旧消息可变字段不能假装成新消息；delta GET 只读取缓存，客户端保留有效本地译文并有界重试。

**原因**：消息 ID 游标只能表达 append，无法表达旧消息翻译字段 mutation；在 GET 内同步调用 AI 会扩大竞态并降低吞吐。将新增消息、delivery 对账和翻译状态分别建模，才能避免游标不推进、重复计数和刷新后译文消失。

**后续**：翻译持久化迁移数据库 revision/event cursor，使用 SSE/WebSocket `translation.completed` 实现跨客户端实时同步；当前旁路 JSON 只作为迁移期缓存。

## 2026-07-11: AI 画像写入采用联系人 revision + savepoint 原子事务

**决策**：每个联系人维护单调 `profile_revision`。Claim 创建/转换必须通过 revision CAS；Snapshot 发布同时校验 current snapshot version 与 profile revision，并保存精确 Claim ID/版本集合。

- Claim + Evidence + revision、Claim transition、旧/新 Snapshot 切换必须完整位于同一个 savepoint；任何冲突不得留下半成品事务。
- 所有 Repository 路径强制验证 account/contact/conversation scope，消息和总结证据必须真实存在且属于同一 scope。
- 任意 `manual_lock=true` Claim 均禁止 Worker transition；冲突只能形成新的待审核建议。
- 默认 Snapshot 只采用 accepted、有效期内且非 restricted Claim；同 key 人工锁定版本优先。
- Repository 在 P0 是唯一画像写边界；数据库复合外键和 PostgreSQL 真实并发集成测试列入 P1 加固。
- AnalysisJob 使用 idempotency key、priority、lease、retry、budget 和父子进度契约；生产 PostgreSQL Worker 使用 `FOR UPDATE SKIP LOCKED`。

**关联规格**：`FR-CON-005..010`、`FR-PLG-005..006`、`docs/sdd/03-data-model.md`、`docs/sdd/04-api-and-events.md`。

---

## 2026-07-11: 人物画像采用 Evidence → Claim → Snapshot，平台接入采用官方 Adapter

**决策**：人物画像不保存为模型反复覆盖的一段文本。聊天消息和总结是 Evidence，结构化事实/观察/推断是 Claim，页面和回复 Prompt 使用可重建 Snapshot。

- 每个 AI Claim 必须有证据、来源类型、置信度、状态、敏感级别和分析版本；人工确认、编辑和锁定优先。
- 会话总结、记忆抽取、画像聚合和批量刷新由 Worker 异步执行，插件仅在真实 Worker readiness 可用时启用。
- AI 回复通过 Context Orchestrator 选择当前相关的已接受信息，不把全部历史和画像直接塞入 Prompt。
- 多平台统一到 Channel Account + Adapter；业务层只消费标准事件和能力声明。
- Telegram 客服首选 Business Connected Bots，Bot API 用于机器人，TDLib 仅用于用户明确授权的完整客户端场景。
- Meta 仅采用 Facebook Page Messenger、Instagram 专业账号和 WhatsApp Cloud API 官方授权；个人 Facebook Profile Inbox 和 Cookie/浏览器自动化明确排除。

**关联规格**：`FR-CON-005..010`、`FR-PLG-005..006`、`FR-CHN-001..005`、`docs/sdd/08-ai-relationship-and-multichannel.md`。

---

## 2026-07-11: 轮询必须由单一 loop owner 在前台按请求完成时间调度

**决策**：Workspace 与账号状态轮询使用 single-flight 请求和 completion-scheduled `setTimeout`，不得使用可能与慢请求重叠的固定 `setInterval`。页面 hidden 时清除常规定时器，visible 后只恢复一次。

- single-flight 不仅约束 HTTP Promise，也必须保证只有一个 loop owner；visibility 恢复不能衍生第二条定时链。
- 请求失败后的清理不能制造未观察的 rejected Promise。
- 自动翻译在前端迁移期只允许一个 worker 串行处理；切换会话或关闭功能必须 abort 当前请求并阻止旧响应回填。
- 发送成功以真实消息 ID 就地替换乐观消息，不再用裸 `setTimeout` 触发额外全量拉取。
- 服务端异步翻译队列仍是 `SDD-P1-05` 的最终目标，本决策只治理迁移期前端并发。

**关联规格**：`NFR-PERF-002`、`NFR-REL-002`、`SDD-P1-05`。

---

## 2026-07-10: 自动翻译可用性必须由插件、消息设置和 Provider 共同决定

**决策**：插件目录显示“已开启”不代表自动翻译可用。运行时唯一有效状态必须同时检查 `plugins.auto_translate`、`message_ops.auto_translate` 和 AI Provider 密钥配置。

- `/api/v1/ai/settings` 返回脱敏后的 `auto_translate.ready/blocked_reason`，前端只依据该有效状态自动展示译文。
- AI 密钥通过业务数据库加密保存；读取只返回 configured/hint，保存后下一次翻译热生效。
- 手动翻译与读取时翻译使用同一运行时 Provider；禁止一个路径读数据库配置、另一个只读启动环境。
- Provider 未配置或调用失败时，前端必须显示可操作提示；不得静默吞错或把原文展示为成功译文。
- Legacy 数字 ID 和 V2 UUID 都是合法消息缓存键，统一字符串化处理。
- 消息读取同步翻译仅作为迁移期实现；后续按 SDD-P1-05 改为异步任务、缓存回填和失败重试。

---

## 2026-07-10: 页面滚动由页面容器负责，根节点保持应用壳固定

**决策**：`html/body/#root` 可保持固定应用壳，但每个主页面必须拥有自己的 `min-height:0 + overflow:auto` 滚动容器，并为底部 TabBar/安全区预留空间。

- 聊天、通讯录、发现、我和账号中心不得依赖 window 滚动。
- 桌面与移动端必须验证 `scrollWidth === clientWidth`，禁止隐藏横向溢出来伪装修复。
- 固定底栏不能截断最后一项；长页面必须能滚动到内容底部。
- 页面壳、账号页按钮、状态徽标和表单统一使用 `.wx-*` 设计 token，避免未定义 CSS 变量导致暗色模式失效。
- React 条件返回必须放在全部 Hooks 调用之后，避免登录状态切换触发 Hooks 数量变化和生产崩溃。

---

## 2026-07-10: 移动聊天采用显式列表/聊天状态，桌面继续双栏

**决策**：`selectedId` 同时作为移动端导航状态：为空时显示会话列表，非空时显示聊天窗；移动聊天内隐藏 TabBar 并由头部返回键清空 `selectedId`。刷新工作区不得在无选择时自动选中首会话。桌面端始终保持 sidebar + chat 双栏。

**原因**：CSS 直接隐藏 sidebar 加上自动选择首会话，会让手机用户永远无法回到会话列表。显式两级状态与微信交互一致，也不会改变桌面信息密度。

---

## 2026-07-10: 乐观消息在取得真实 ID 前不得进入翻译链

**决策**：`tmp-*`、pending、failed 消息不调用翻译 API；回复成功后使用服务端 `local_message_id/message_id` 替换临时 ID。服务端刷新按 `role+content` 匹配并保留本地 `sent` 状态。

**原因**：临时字符串 ID 无法通过后端消息 ID 校验，会造成每次发送后的 422；刷新若直接重建对象，又会冲掉已发送状态。

---

## 2026-07-10: 高频轮询只能在业务数据变化时替换 React 状态引用

**决策**：账号和会话轮询必须保持稳定引用；服务器返回值语义未变化时不得无条件 `setState(newArray)`。聊天初始加载 effect 只能依赖稳定的会话 identity 和明确配置标量，不能依赖整个 settings/account 对象。

**原因**：账号 3 秒轮询每次创建新数组，令 Workspace fetch callback 重建并重新执行初始化 effect；同时 SettingsProvider 刷新生成新 `uiSettings` 对象，导致 ChatPane 清空消息、显示骨架、重载并滚底，形成周期性闪烁。

**约束**：
- 轮询数组在深度等价时保留旧引用；
- 当前值通过 ref 提供给稳定 callback；
- 初始加载以 `standalone:conversationId` 或 `legacy:userId` 为 identity；
- 自动翻译必须按 message ID 记录 in-flight，禁止同一条消息并发重复翻译；
- 验收必须采集连续 DOM 样本，确认首次加载后消息数、容器高度和 scrollTop 稳定。

**关联规格**：`FR-MSG-002`、`FR-MSG-007`、`SDD-P1-05`、`SDD-P2-06`。

## 2026-07-10: 当前聊天的刷新、发送和翻译必须使用同一数据面

**决策**：Legacy 与 V2 可在列表聚合，但进入具体会话后，刷新、发送、落库、消息 ID 与翻译必须锁定该会话的数据面和账号。

- V2 会话按 `conversation_id` 刷新独立消息 API，不得因 Legacy 增量接口存在而跳过刷新。
- V2 发送使用 `conversation.account_id + remote_jid` 调用 Bridge，成功后写独立 `messages`；禁止走 Legacy `/api/reply`。
- 翻译 API 接受整数和 UUID message ID；缓存键保持字符串化，不把 V2 UUID 强转为整数。
- 全局 AI 配置入口归入“我 → 全局 AI 设置”；聊天页只保留当前联系人相关 AI 覆盖，不承载全局 Provider/模型管理。
- 账号 offline 时不得声称真实同步已验收；代码测试、Bridge health 与真实账号在线消息是不同验收层级。

---

## 2026-07-10: 收件箱采用平台→账号两级筛选并以账号范围标识会话

**决策**：控制台聊天首页的 `ALL` 聚合所有接入平台和账号；一级筛选平台，二级筛选该平台账号（如 `ALL → WA → WA1/WA2/WA3`）。迁移期 Legacy 与 V2 在前端统一排序，但保留各自数据源和发送链。

- 会话身份使用 `source + conversation_id/user_id` 生成 `conversation_key`，不得只用 JID；同一 JID 在不同账号下是不同会话。
- 每条会话和联系人必须展示平台/账号上下文；通讯录同样按平台和账号筛选，不按电话号码或 JID跨账号合并。
- 页面聚合不等于数据库混写：Legacy 保留兼容读取，V2 继续以独立业务库为真源。
- 后续接入 Telegram 等平台时沿用同一一级平台、二级账号模型，不为每个平台复制聊天页面。

---

## 2026-07-10: V2 账号会话必须从独立业务库按 account_id 展示

**决策**：账号中心中的 V2 账号状态与聊天首页必须使用同一独立业务数据库。聊天列表新增 `all|account_id` 作用域；独立会话详情使用 conversation UUID，不再用 JID 查询 Legacy `state.db`。

- 页面不能因迁移期保留 Legacy API 而隐藏已成功落入独立库的 V2 消息。
- 聚合视图中每条会话必须携带 `account_id` 和账号名；单账号筛选必须在服务端查询层生效。
- 账号切换必须清空旧会话选择，避免把 A 账号选中的联系人内容显示在 B 账号上下文。
- Legacy 消息链暂时保留作为回滚兼容，但不能再作为 V2 账号的显示真源。
- 当前实例仅有一个 V2 业务账号，因此不能将“两个账号同时在线和隔离”标记为完成。

---

## 2026-07-10: Legacy 网页直发成功必须同步写回页面消息源

**决策**：迁移期 `/api/reply` 仍通过 Legacy Bridge 发送时，只有底层明确返回成功和真实 WhatsApp message ID 后，FastAPI 才把 outbound assistant 消息写入 Hermes `state.db`。

- 页面消息源仍是 `state.db`，不能只依赖浏览器 optimistic bubble。
- 写回保存本地 message ID 与 `platform_message_id`；API 同时返回两者供前端稳定合并。
- 发送失败不得落库为成功消息，前端保留失败 bubble、错误文案和原地重试。
- 该方案只解决迁移期 Legacy 同步缺口；Bridge V2 正式发送仍按业务库 Outbox/事件回执规格实现。

---

## 2026-07-10: Bridge V2 使用持久化 spool，并在真实账号验收前保持影子模式

**决策**：Bridge V2 的事件投递采用每账号单 writer 的磁盘 FileSpool；任何账号状态、消息或回执先持久化，再发送至 FastAPI 内部事件接口。

- 每账号仅一个 `EventSink/FileSpool` owner，重启 replay 后注册账号必须复用同一 owner。
- 事件唯一边界为 `(account_id,event_id)`；相同 ID 的 canonical envelope 不一致必须显式冲突，不得静默覆盖。
- FastAPI 以单事务写入事件、联系人、会话和消息；状态与回执按 sequence/rank 单调。
- QR、session credential、底层路径和 token 不进入 webhook、状态 API 或用户响应。
- Legacy Bridge `3000` 在 V2 真实扫码、收发、session 恢复和双账号验收前保持运行；V2 使用 `3100` 影子验证，不提前切流。
- 无真实 WhatsApp 账号的 health/auth/create/status/stop 验证只能证明运行和安全门禁，不能将需求标记为 `Verified`。

详细实现：`docs/plans/2026-07-10-bridge-v2-account-center.md` Task 5/6。

---

## 2026-07-10: Bridge V2 未配置时 fail-closed，账号 UI 不伪造登录

**决策**：账号控制面可以先于独立 Node/Baileys Bridge V2 上线，但不得用假 QR、静态状态或数据库预写 `online` 冒充已登录。

- `WHATSAPP_BRIDGE_INTERNAL_TOKEN` 未配置时，Bridge 写操作返回结构化 `bridge_not_configured`。
- 创建账号只有在 Bridge 注册成功后才对用户视为成功；注册失败补偿删除业务记录。
- `connect` 只返回已受理，不提前改为在线；账号状态最终由后续 Bridge 事件更新。
- 新账号默认 `auto_reply_mode=off`，真实连接和事件链验收前不默认开启自动回复。
- 用户可见设置不再暴露 Hermes profile/path/CLI，Legacy 兼容仅保留在服务器迁移层。

详细计划：`docs/plans/2026-07-10-bridge-v2-account-center.md`。

---

## 2026-07-10: SDD 成为强制开发规格

**决策**：`docs/sdd/` 成为本项目需求、架构、数据模型、API、优化清单、开发流程和迁移策略的唯一权威规格源。

所有后续任务必须：

1. 先读取并确认相关 SDD；
2. 绑定需求 ID；
3. 复杂任务先写实施计划；
4. 使用 RED → GREEN → REFACTOR；
5. 完成规格符合性和代码质量审查；
6. 通过全量门禁和真实运行验证；
7. 更新 SDD 状态及项目四文件。

`TODO_AGENT.md` 只作为当前执行视图；旧 `docs/SDD.md` 和 `docs/ARCHITECTURE.md` 不再承载完整权威规格。紧急修复也必须在同一任务内补齐 SDD 和回归测试。

---

## 2026-07-10: 独立运行、问鼎 AI 与多 WhatsApp 账号架构

**现状证据**：

- 当前 FastAPI 从 Hermes profile 的 `config.yaml`、`state.db` 和 JSON sidecar 读取配置/消息。
- 当前发送路径先调用本机 `127.0.0.1:3000` Bridge，失败后回退 `hermes --profile ... send`。
- 当前 Bridge 由 Hermes gateway 拉起，进程内只有一个全局 Baileys `sock` 和一个内存消息队列。
- 当前数据表没有 `account_id`，`workspace_id` 实际只等于 `source=whatsapp`，不能隔离多个 WhatsApp 账号。

**决策**：采用“FastAPI 控制面 + 独立多账号 Baileys Bridge + 业务数据库 + Worker + React 管理台”。

- 运行时不依赖 Hermes CLI、Hermes profile、Hermes gateway 或 Hermes `state.db`。
- 问鼎 AI 使用 OpenAI-compatible API：`https://wendingai.future1.us/v1`。
- 全局默认模型固定为 `gpt-5.3-codex-spark`；优先级为联系人 override > 账号 AI profile > 全局默认。
- 每条联系人、会话、消息、任务必须带 `account_id`；联系人全局键是 `(account_id, remote_jid)`。
- Bridge 每账号独立 socket 和 session 目录，通过 webhook 幂等推送消息事件。
- 发消息使用数据库 Outbox；定时与群发由真实 Worker 执行。
- 旧 Hermes 数据仅通过只读 importer 一次性迁移，迁移后不参与运行。

**详细实施方案**：`docs/plans/2026-07-10-standalone-wendingai-multi-account.md`。

---

## 2026-07-09: StaticFiles `/assets` mount path bug

**问题**：Starlette StaticFiles mount 到 `/assets` 时，URL path `/assets/index.js` 会被 strip `/assets` 前缀，然后查找 `directory/index.js`。但文件实际在 `dist/assets/index.js`，导致 404。

**决策**：mount 时 `directory` 参数指向 `frontend_dist / 'assets'`，而非 `frontend_dist`。

```python
# 错误（会导致 404）
app.mount('/assets', StaticFiles(directory=frontend_dist), name='web-assets')

# 正确
app.mount('/assets', StaticFiles(directory=frontend_dist / 'assets', check_dir=True), name='web-assets')
```

**涉及文件**：`src/whatsapp_chat_system/web_api.py`

---

## 2026-07-09: SPA serving 方案

**决策**：FastAPI 直接挂载 `web/dist`，不使用 nginx 静态文件服务。

**优点**：
- 单一进程，无需额外 web server
- `--web-dist` CLI 参数显式控制
- catch-all路由 `/{full_path:path}` 处理 SPA 路由

**验证**：
```
/api/* → FastAPI handlers
/assets/* → StaticFiles (dist/assets/)
/ → dist/index.html (catch-all)
```

---

## 2026-07-09: 前端 CSS 类名规范

**决策**：统一使用 `.wx-*` 前缀，避免与第三方库冲突。

设计 token：
- `--wx-brand`: 主品牌绿 `#07C160`
- `--wx-bg`: 背景 `#EDEDED`
- `--wx-surface`: 面板 `#F5F5F5`
- `--wx-text`: 主文字 `#1A1A1A`
- `--wx-text-secondary`: 次文字 `#888`
- `--wx-text-muted`: 弱文字 `#999`
- `--wx-border`: 分割线 `#E5E5E5`

组件类：
- `.wx-shell` / `.wx-shell-content` / `.wx-shell-header`
- `.wx-tab-bar` / `.wx-tab-btn`
- `.wx-list-item` / `.wx-avatar` / `.wx-badge`
- `.wx-bubble` / `.wx-composer`
- `.wx-skeleton` / `.wx-spinner`
- `.wx-modal` / `.wx-primary-btn`

---

## 2026-07-09: i18n 管理策略

**决策**：4 语言（en/zh/th/lo）全部对齐，所有 key 在 4 个 block 的行号严格对应。

**工具**：sed 精确行号插入（不依赖 patch 的字符串匹配）

**验证**：`grep -n "^    key:" i18n.js` 对齐所有 4 个 block

---

## 2026-07-08: pinned 状态来源

**决策**：pinned 列表使用后端 `/api/conversations` 返回的 `item.pinned` 布尔字段，不在前端维护独立 state。

前端仅维护 `Set<user_id>` 用于快速查找，pinned 分组直接从 conversations 列表 filter。

---

## 2026-07-10: 增量消息使用严格 ID 游标

**问题**：过滤条件为 `m.id > after_id`，但旧查询按 `timestamp, id` 排序。当历史时间戳乱序且分页受限时，前端推进 ID 游标后可能永久跳过较小 ID 的消息。

**决策**：

- SQLite 增量查询严格 `ORDER BY m.id ASC`
- API 返回 `next_after_id` 和 `has_more`
- 前端连续读取后续批次，直到 `has_more=false`

时间戳仅用于展示，不参与增量游标推进。

---

## 2026-07-10: 发送成功必须是显式真值

**决策**：发送链路只有在底层结果明确返回 `success is True` 时才算成功。缺失、`false`、异常、非 2xx 均作为失败处理。

- 单发失败由 API 返回 502 和可重试标记
- 前端失败消息保留原文、目标与发送模式，允许原地重试
- 群发返回每个目标结果以及成功/失败统计，不再总是返回成功

---

## 2026-07-10: 左滑操作与纵向滚动手势分离

**决策**：会话操作层放在内容层下方，默认不可见。手势移动超过阈值后先锁定方向：横向才更新位移，纵向交还列表滚动。

同时要求：

- `touch-action: pan-y`
- 同时只允许一行展开
- 滑动完成后的 click 不打开会话
- 删除需要用户确认，接口失败必须反馈
