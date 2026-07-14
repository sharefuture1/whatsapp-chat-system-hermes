# 优化待办规格

> 本文档是所有待优化项目的权威清单。`TODO_AGENT.md` 只作为当前执行视图，不能新增与本文档冲突的需求。

## 1. 状态定义

- `Approved`：规格已批准，等待开发；
- `In Progress`：已有开发任务和测试；
- `Implemented`：代码完成，待全量验收；
- `Verified`：已通过规格验收；
- `Blocked`：注明阻塞条件。

## 2. P0：独立化和可靠核心链路

### SDD-P0-01 独立配置与问鼎 AI Provider

- 状态：`Implemented`
- 需求：FR-CORE-001~003、FR-AI-001~007
- 目标文件：
  - `src/whatsapp_chat_system/settings.py`
  - `src/whatsapp_chat_system/ai/provider.py`
  - `src/whatsapp_chat_system/ai/service.py`
  - `src/whatsapp_chat_system/rewriter.py`
- 验收：
  - 默认 URL/模型严格为问鼎 AI 和 `gpt-5.3-codex-spark`；
  - mock server 确认调用 `/v1/chat/completions`；
  - 401/429/5xx/timeout 有结构化错误与有限重试；
  - API/log 不泄露 key；
  - 没有 Hermes config 时 AI 配置仍能加载。

### SDD-P0-01A Standalone systemd 部署合同

- 状态：`In Progress`（独立 API runtime/TDD 已落地；systemd/static assets 仍仅为合同草案，尚未完成生产安装或切换验收）。
- 需求：FR-CORE-001、FR-CORE-002、FR-ACC-003、MIG-001、MIG-002、QA-001。
- 当前进度：仓库内 API unit 已改为 `/opt/whatsapp-chat-system` 的无 profile `serve` 启动；新增 Bridge V2 unit，固定 loopback `127.0.0.1:3100` 与独立 `/var/lib/whatsapp-chat-system/bridge` runtime root。两个 unit 都只引用受控 `/etc/whatsapp-chat-system/*.env`，不包含真实秘密或 Hermes 路径。
- 验收：
  - 静态契约测试确认 API `ExecStart` 没有 `--profile`，API/Bridge units 不包含 Hermes runtime 路径；
  - API 经 `CHAT_SYSTEM_RUNTIME_DIR`、`DATABASE_URL`、`WHATSAPP_BRIDGE_INTERNAL_TOKEN` 取得独立运行配置；
  - Bridge 经独立 runtime root、loopback host/port 和同一内部 token 启动；
  - 生产切换前完成 unit 安装、live/ready、日志无 Hermes runtime 路径和真实 WhatsApp 收发验证。
- 未完成：不触碰真实生产 unit；MIG-8 安装/切流和真实 WhatsApp 验收完成前不得标记 `Verified`。

### QA-001 独立运行切换质量门禁

- 状态：`In Progress`
- 每项独立化变更先有失败自动测试，再以 focused tests、`git diff --check` 和适用的构建/健康检查验证。
- 任何未执行生产安装、真实 QR/收发或回滚演练的切换工作只能为 `Implemented` 或 `In Progress`，不得以静态资产替代生产 `Verified`。

### SDD-P0-02 新业务数据库与账号隔离

- 状态：`In Progress`
- 实施计划：`docs/plans/2026-07-10-p0-02-account-scoped-database.md`
- 需求：DATA-001~007、FR-ACC-003、FR-CON-003
- 验收：
  - 两账号相同 JID 可并存；
  - 查询无跨账号泄漏；
  - 重复 WhatsApp message ID 幂等；
  - Alembic upgrade/downgrade 测试通过。

### SDD-P0-03 独立 Bridge V2 单账号

- 状态：`Implemented`
- 当前进度：账号控制面、独立 Node/Baileys Bridge、持久化 spool、内部事件接收、状态/消息/回执事务落库均已实现并通过全量测试与 3100 无真实账号安全影子验证。真实 WhatsApp 扫码、session 恢复、真实收发/回执仍待测试账号验收，完成后才可进入 `Verified`。
- 实施计划：`docs/plans/2026-07-10-bridge-v2-account-center.md`
- 验收：
  - 不运行 Hermes gateway 仍可扫码、连接、收发和恢复 session；
  - Bridge 有 live/ready health；
  - webhook 失败进入持久化 spool；
  - 发信无真实 message ID 时判失败。

### SDD-P0-04 Bridge V2 多账号

- 状态：`In Progress`
- 当前进度：真实扫码账号已在线，独立数据库已接收其联系人/会话/消息；新增 `/api/v1/conversations` 账号范围查询和前端“全部账号/单账号”筛选，修复新账号数据已落库但页面仍固定读取 Legacy `state.db` 的断点。当前运行实例只确认 1 个 V2 业务账号在线，尚未达到“两账号同时在线”验收。
- 验收：
  - 至少两个账号同时在线；
  - A 断线/登出/删除不影响 B；
  - A 会话不会使用 B socket 发送；
  - session、spool、限速和状态完全隔离。

### SDD-P0-05 Outbox 可靠发送

- 状态：`Implemented`（代码、单机 Worker 与自动化回归已落地；独立生产切流和真实 WhatsApp 投递尚未验收，不得标记 `Verified`）。
- 需求：FR-MSG-004~006、MSG-OUTBOX-001~005。
- 当前实现：
  - `outbox_messages` 与业务 `messages` 在同一事务创建；回复、定时和群发统一返回 `202 queued`，不提前声明 `sent`；
  - `idempotency_key` 全局唯一，同 key 重试返回原业务消息和 Outbox 记录，不会再次投递；
  - `OutboxDispatcher` 在 Standalone lifespan 内轮询，使用 lease owner/expiry claim、Bridge idempotency key、真实 WhatsApp `message_id` 与指数退避；
  - 过期 lease 可回收；旧 Worker 不能覆盖新 owner 的最终状态；Bridge receipt 持久化可跨重启恢复。
- 验收：
  - [x] API 返回 queued，而非提前 sent；
  - [x] Worker 重启后 pending/receipt 可恢复；
  - [x] 幂等 key 防重复发送；
  - [x] lease、失败重试和 Bridge receipt 有自动化测试；
  - [ ] 独立生产 Worker 的真实 WhatsApp 发送、回执和重启恢复验收。

### SDD-P0-06 定时任务真实 Worker

- 状态：`Implemented`（Standalone V1 实现与自动化回归已落地；多实例和真实生产账号验收待完成）。
- 当前实现：
  - `GET/POST/DELETE /api/v1/schedule` 基于 Outbox；创建仅接受未来 UTC 时间，返回 `202`；取消会终止未完成任务；
  - `available_at` 到点后由 Outbox Dispatcher 投递；账号离线/Bridge 瞬态错误进入可检查的 pending/dead 与 `last_error` 状态；
  - 迁移期 Legacy `/api/schedule` 仍保持 503，前端只有检测到 Standalone V1 能力后才应启用真实创建入口。
- 验收：
  - [x] 到点进入真实 Outbox 投递路径；
  - [x] 可取消且有追踪状态；
  - [x] 离线/暂态错误可重试并保留错误原因；
  - [ ] 多 Worker 分布式 claim 验收；
  - [ ] 真实生产账号到点发送、重启恢复验收。

### SDD-P0-07 群发后台任务

- 状态：`In Progress`。
- 当前实现：`POST /api/v1/broadcast` 对每个有效目标创建独立的 Outbox 记录，返回 `202`、queued/rejected 明细；`GET /api/v1/broadcast` 按 batch 聚合每个目标的完成/失败状态。迁移期 Legacy `/api/broadcast` 仍返回 503。
- 已完成验收：后台异步投递、逐项结果、重复目标去重、单目标 idempotency key。
- 剩余验收：
  - 账号级限速和抖动；
  - 显式暂停、取消、续跑；
  - 独立 `broadcast_jobs / broadcast_recipients` 状态模型和大批量分页；
  - 多 Worker 与真实生产账号的端到端验收。

### SDD-P0-09 24x7 AI 自动回复可靠性

- 状态：`Approved`
- 目标：AI 自动回复必须由独立的持久化 Job + Outbox 链路驱动，不能在 webhook 请求线程同步调用模型，也不能依赖浏览器页面打开。
- 触发：仅处理入站、非系统、非自己发送的消息；账号 `enabled=true`、`auto_reply_mode=auto`、会话 `ai_mode=auto` 且联系人未显式关闭时才创建任务。
- 幂等：以 `account_id + wa_message_id + policy_revision` 为唯一幂等键；同一入站消息最多产生一个自动回复 Job 和一个 Outbox。
- 可靠性：AI Job 状态为 `pending/claimed/running/retry/completed/failed/dead/cancelled`；Provider 超时、429、5xx 使用指数退避；不可重试错误进入 dead；Outbox 使用 lease、真实 WhatsApp message ID 和回执对账。
- 安全：管理员配置全局策略、模型、限速、工作时间和暂停开关；普通用户只能看到状态，不能修改 Provider、Prompt、模型、限速或全局开关；联系人可以由管理员单独暂停自动回复。
- 防骚扰：每账号/联系人限速、冷却窗口、每日预算、连续失败熔断；AI 回复前再次检查账号在线、策略和消息是否已被人工回复。
- 运维：`/api/v1/automation/health` 返回 worker heartbeat、pending/running/retry/dead、最近错误和熔断状态；systemd 必须自动重启，服务启动后不依赖 Web 页面。
- 验收：服务停止/重启后 Job 可恢复；重复 webhook 不重复回复；AI 超时可重试；Bridge 离线进入 retry；管理员暂停立即阻止新任务；真实账号 24 小时运行观测无永久 pending/dead 增长。

- 状态：`In Progress`（代码与 API 已落地，但未做真实部署切流；待生产验收后再标记 `Verified`）。
- 需求：`FR-PLG-007`、`FR-PLG-008`、`FR-AI-012`。
- 当前进度：
  - 受控人设库 `src/whatsapp_chat_system/personas.py` 内置 `default / tong-jincheng / professional-service / mature-uncle`，每条人设仅含审计过的 prompt 与展示元数据。
  - Rewriter 已接收 `reply_overrides.persona_id`，`rewrite.persona` 字段返回当前人设元数据。
  - V1 API：`GET /api/v1/personas`、`PUT /api/v1/personas/{id}/enable`、`PUT /api/v1/contacts/{contact_id}/persona`。
  - 前端聊天页 `…` 菜单 → 人设 picker；头部 `personaCurrent` 实时反映；预览条同步显示当前人设。
  - 前端发现页"AI 人设"分类展示内置人设卡片，禁显任何外部源/仓库信息。
  - 四语 i18n key 同步、`t()` 使用 `??`，未知 key 不被吞掉。
- 验收：
  - 真实调用 V1 列表/启停/分配人设接口，回归 200/401/404/422。
  - 重写器在选中/卸载/未知/插件关闭任一情况下都不注入未授权 prompt。
  - 真实老挝语→中文 AI 探针：选择 `tong-jincheng` 后回复风格被该 prompt 影响。
  - 默认策略（不选人设）走 `default` 且不引入额外延迟。
- 未完成：未在生产启用；未与真实 WhatsApp 账号联动验收。

## 3. P1：产品可用性

### SDD-P1-01 前端 WhatsApp 账号中心

- 状态：`In Progress`
- 当前进度：微信式列表/详情/状态/高危删除 UI 已接真实账号 API，旧 Hermes profile/path/CLI 入口已从用户可见设置移除；真实二维码和实时状态依赖 Bridge V2 后续闭环。
- 实施计划：`docs/plans/2026-07-10-bridge-v2-account-center.md`
- 当前缺陷：账号中心控制面已实现，但真实登录仍等待独立 Bridge V2 与事件链。
- 验收：UI 内创建、QR、实时状态、重连、登出、停用、删除；不出现 Hermes profile 概念。

### SDD-P1-02 真实未读计数

- 状态：`Approved`
- 验收：入站增加、进入会话/显式已读清零、跨设备状态一致；不使用前端估算冒充真实值。

### SDD-P1-03 独立联系人模型

- 状态：`Approved`
- 验收：联系人不依赖现有会话；支持备注、标签、分组、语言、搜索和账号筛选。

### SDD-P1-04 微信式信息架构收敛

- 状态：`Implemented`
- 已实现：聊天、通讯录、发现、我、账号中心已统一使用独立页面壳、滚动容器和移动端安全区；全局 AI 配置保持在“我”页；聊天头部仅保留返回、联系人名称/状态和“…”；Emoji、直发、AI 智能、翻译模式进入输入区折叠面板；双方使用微信式方形头像和左右镜像气泡。发现页收敛为运营概览 + 受控 AI 人设；插件目录迁入“我 → 插件中心”；定时/群发仅在插件中心二级任务页露出。
- 剩余内容：
  - 把“发现”正式更名为“工作台”（若产品确认命名）；
  - “我”页继续只保留操作员和全局设置；
  - 账户中心在 Bridge V2 实时 QR/状态链完成后验收。

### SDD-P1-11 我页 → 设置二级页（取代模态）

- 状态：`Implemented`
- 需求：FR-UI-008、SDD-P1-04 收敛方向
- 当前问题：`SettingsPanel` 仍是覆盖模态，5 个 Tab 在小屏切换拥挤；用户感知“设置功能分散、不像微信”；“我”页不显示登录用户名、QR 入口不显眼；Discover 页面人设卡片不可点；Contacts 缺空状态图。
- 目标：
  - 把“设置”从模态改为“我”→全屏二级页（与微信“设置”一致），子级也是“账号与安全/通用/AI/聊天/关于”全屏二级页，不再使用 modal 弹窗。
  - 所有 `wx-cell-group` 内的 row 都用 `cell` 风格：左侧图标、中部标题/副标题、右侧状态/箭头，触觉高亮（active 状态），整行可点。
  - 取消 `SettingsPanel` 中 reply/ai/ui/security 4 个 Tab；改用独立二级页通过 App.jsx 路由控制。
  - “我”页顶部 hero 改为真实登录名、当前角色、QR 入口、消息模板按钮，靠近微信 “我” 视觉。
  - Discover 页面人设卡片要么去掉（“我”入口继续），要么真正接 `onAssignPersona`。本轮只保留 Discover 的运营概览，人设迁移至聊天页头部 picker + 我页 → 通用。
  - Contacts 页面空状态、Discover 页面空状态补完整。
  - 4 种语言同步新增“设置 → 账号与安全/通用/AI/聊天/关于”等子页标题。
- 验收：
  - 任何路径下都不再出现覆盖全屏的 settings modal 弹窗（账号中心二级页保持）；
  - 桌面 1440×900 / 移动 390×844 都能整行触达，键盘可达、focus-visible 可见；
  - npm run build 通过、243 Python 测试 + Web 测试不退化；
  - 自动化守卫：i18n 4 语言 key 一致、空状态文案不空。
- 不破坏：
  - 联系人自动回复开关仍在聊天页抽屉 + 我 → 联系人 AI 配置入口；
  - 旧 SettingsPanel 仅在 chat drawer 联系人规则使用（API 行为不变）。


### SDD-P1-05 翻译异步化

- 状态：`In Progress`
- 新增要求：翻译结果必须持久化到 Standalone 业务数据库，不以浏览器 localStorage 作为真源。
- 翻译采用会话上下文批处理：默认以当前待翻译消息及其之前最多 10 条消息组成上下文窗口，单次模型调用统一翻译并校正窗口内译文；已完成且未发生内容变化的消息不得重复调用 Provider。
- 页面优先读取数据库已有译文；缺失译文才创建一次批处理任务/请求，完成后批量回填并展示。
- 管理员可在设置中配置上下文窗口上限（默认 10，允许范围 1~20）、批量翻译开关和翻译目标语言；普通用户只能使用管理员启用的有效策略，不得修改模型、Prompt、窗口上限或 Provider 参数。
- 失败任务必须保留结构化错误和重试时间，不能把原文伪装成译文。
- 验收：同一会话连续打开不重复请求；翻译结果跨浏览器/跨登录可见；窗口内上下文一次性翻译；普通用户无法修改管理员策略；数据库迁移、API、前端展示和真实 Provider 测试通过。
- 旧的浏览器缓存只作为加速层，不得覆盖数据库较新的译文。

- 已实现：插件开关、消息设置和 AI Provider 形成统一有效门禁；运行时加密配置热生效；Legacy 整数 ID 与 V2 UUID 均可翻译；失败向 UI 返回可操作错误，不再静默或把原文伪装成译文；前端按 message ID 记录 in-flight 请求，避免轮询和状态更新期间重复翻译；译文内嵌所属气泡以保持稳定布局。
- 已验证：真实 Provider 老挝语→中文探针成功，Provider 配置与翻译 Worker 使用同一运行时设置。
- 剩余验收：消息读取已改为 cache-only，不再同步触发 Provider；本轮已修复单客户端轮询、V2刷新和失败重试。仍需将翻译缓存迁移数据库 revision/event cursor，并提供 SSE/WebSocket 跨客户端实时更新，才能进入 `Verified`。

### SDD-P1-06 插件完整接线

- 状态：`In Progress`
- 已实现：`auto_translate` 同时控制读取时翻译和手动翻译 API；`quick_reply` 控制 AI 预览；`persona_styles` 控制受控人设目录与联系人分配；`memory`、`analytics` 有对应读取 API。插件中心按后端真值显示 `available / unavailable_reason / status_when_on / hooks`；不可用插件禁用开关且隐藏删除动作；刷新、筛选、加载、错误和空状态可见。`SchedulerCenterPage`、`BroadcastCenterPage` 只显示历史/状态及未来入口，不会将 503 当成成功。
- 未接线能力：定时、群发、TTS、媒体、自动标签、跟进均为 `available=false`；原因随条目返回。
- 验收：
  - 每个 `available=true` 插件有真实 API/worker gate 且开关会影响该 gate；
  - 无 hook 或无 Worker 时 `available=false`，写操作不可被 UI 伪装为成功；
  - 四语言 key 集合相同且无重复；`t()` 仅对 `null`/`undefined` 回退，不吞掉空字符串显示值；
  - 定时/群发完成 SDD-P0-05/06/07 后再把对应条目改为可用。

### SDD-P1-07 认证升级

- 状态：`Approved`
- 内容：HttpOnly Cookie、CSRF、服务端 session hash、移除弱默认密码、审计、预留 RBAC。

### SDD-P1-08 数据库分页与索引

- 状态：`Approved`
- 验收：会话、消息、搜索使用数据库游标分页；有 explain/index 验证；大数据集不全表装入 Python。

### SDD-P1-09 运行配置数据库化

- 状态：`Approved`
- 当前缺陷：多个请求写 JSON，缺文件锁/事务。
- 验收：设置、插件、会话操作和任务迁移数据库；必要 JSON 写入使用原子替换。

### SDD-P1-10 消息同步 gap 调查与修复

- 状态：`Implemented`
- 已修复：Legacy 迁移期网页直发成功后，将 outbound assistant 消息及 WhatsApp message ID 同事务写回 `state.db`；刷新/增量 API 不再让成功气泡消失或误留感叹号。
- 已修复：Legacy 同会话 delta 使用 single-flight/coalesced 调度，慢响应不会被下一 tick 判旧；相同 ID 用 upsert 对账且只统计真正新增消息，AI assistant 记录可稳定推进游标并进入网页。
- 剩余阻塞：仍需真实 WhatsApp 断线重连、批量历史、乱序/重复事件和 Bridge V2 多账号数据才能完成端到端 `Verified`。
- 验收：断线重连、批量历史同步、乱序事件和重复事件均无永久 gap；网页直发成功后刷新仍能看到同一条消息。

### SDD-P1-07 联系人自动回复控制面

- 聊天详情必须展示联系人级自动回复开关、当前状态和保存结果。
- 开关写入 `ContactAIOverride.auto_reply_enabled`，账号必须在线且全局 `auto_reply_mode=auto` 才会实际触发；关闭后新入站消息不得创建 AI Job。
- 列表/会话 API 返回 `auto_reply_enabled`，前端不得用本地状态伪造服务端状态。
- 高级模型/Prompt 配置仅管理员可见；普通用户只可使用授权的联系人自动回复开关。
- 验收：打开/关闭持久化、刷新保持、无联系人会话返回明确 409、跨账号不能读写、Worker 遵循开关。



### Phase 1：数据层与同步边界

- 统一 `/api/v1` API client、认证、请求去重、短 TTL 缓存和 mutation 失效。
- App/页面不直接裸调用 fetch；feature hooks 负责 query/mutation。
- 会话与消息使用稳定 query key、cursor 和服务端数据真源。
- 关联计划：`docs/plans/2026-07-14-engineering-phase1-data-layer.md`。

### Phase 2：事件驱动同步

- SSE/WebSocket 增量事件、cursor 恢复、前端缓存精确更新。
- 轮询只作为断线补偿，不作为主要实时同步机制。

### Phase 3：翻译与 AI Job

- 数据库译文表、最近 10 条上下文批处理、结构化 AI 输出、管理员策略和普通用户只读策略。
- AI 生成与 Outbox 投递拆成可追踪任务，支持 retry/dead/cancel。

### Phase 4：媒体与可观测性

- 媒体下载、权限代理、Range、对象存储；统一 request/job/event 指标与告警。



### SDD-P2-01 CSS 治理

- 状态：`Implemented`
- 已实现：聊天、通讯录、发现、我、账号中心/详情/QR 使用统一的 flex/min-height/overflow 页面壳；桌面和 390px 移动视口无横向溢出，通讯录和发现页拥有可用的独立滚动容器；补齐账号页缺失类、设计 token 与底部安全区。
- 剩余验收：继续清理重复规则和旧 `.wx-tabbar*`，建立 JSX 类名自动扫描并将 Playwright 检查纳入仓库测试。

### SDD-P2-02 统一 SVG Icon System

- 功能性 emoji/字符全部替换；
- 提供统一 size/stroke/currentColor；
- 为 TabBar 和按钮增加渲染回归测试。

### SDD-P2-03 Avatar 与媒体体验

- 真实头像、失败回退、懒加载；
- 图片/语音/视频/文档消息有明确状态和失败提示。

### SDD-P2-04 可访问性

- 状态：`In Progress`
- 已实现（2026-07-14）：全局键盘 `:focus-visible` 焦点环（鼠标/触摸不受影响）；`prefers-reduced-motion` 下关闭装饰性过渡与动画；静态回归 `web/tests/uiPolishAccessibility.test.js`。
- 剩余：
  - dialog focus trap；
  - aria-live；
  - 键盘操作；
  - 色彩对比。

### SDD-P2-05 深色模式和语言实时切换

- 默认跟随系统；
- 切换无需刷新；
- 全部语言 key 集合一致。

### SDD-P2-06 Playwright 主链路

- 状态：`In Progress`
- 本轮已用生产站点和有效服务端会话完成桌面 1440×900、移动 390×844 的聊天/通讯录/发现/我页面审计；控制台无 React 错误，页面无横向溢出，滚动容器存在，截图证据已生成。
- 剩余：把临时审计脚本转为仓库内可重复测试，并覆盖以下主链路：

- 登录；
- 账号切换；
- 会话滚动；
- 左滑操作；
- 聊天发送/失败重试；
- QR 页面；
- 插件开关；
- 移动端输入和 safe area。

### SDD-P2-07 统一错误与日志

- FastAPI 全局异常映射；
- request ID；
- 结构化日志；
- 前端错误文案和重试动作；
- 敏感字段脱敏。

## 5. 已验证基线，不得回归

- 左滑后才显示置顶/删除；
- 左滑与纵向滚动方向锁；
- TabBar 和按钮 SVG 使用显式尺寸/currentColor；
- 发送只有显式真实成功才显示成功；
- 失败消息可重试；
- 增量消息严格按 ID 游标；
- 快速切换联系人不串线；
- 聊天移动端隐藏根 TabBar；
- 输入框自动增高，IME Enter 不误发；
- 查看历史时不强制滚底；
- CORS OPTIONS 不被 auth 拦截；
- i18n key 全语言对齐；
- StaticFiles `/assets` 路径正确。

任何重构必须保留对应回归测试。
