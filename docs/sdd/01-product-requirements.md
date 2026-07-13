# 产品需求规格

## 1. 产品定位

一套面向客服、销售和私域运营人员的独立 WhatsApp 多账号工作台。系统统一管理账号、联系人、会话、消息、AI 回复、翻译、定时发送、群发和插件，不向最终用户暴露 Hermes 概念。

## 2. 用户角色

- **Owner**：管理部署、账号、AI Provider、密钥引用、用户和审计。
- **Admin**：管理 WhatsApp 账号、操作员、插件、群发和策略。
- **Operator**：处理会话、生成/编辑/发送回复、备注联系人。
- **Viewer**：只读查看会话、统计和审计。

首阶段可保持单管理员登录，但数据结构和 API 不得阻塞后续 RBAC。

## 3. 功能需求

### 3.1 独立运行

- **FR-CORE-001 [Approved]**：正式运行链路不得依赖 `hermes` 可执行文件。
- **FR-CORE-002 [Approved]**：正式运行链路不得读取 Hermes profile 作为配置真源。
- **FR-CORE-003 [Approved]**：正式消息库不得使用 Hermes `state.db` 作为实时真源。
- **FR-CORE-004 [Approved]**：旧 Hermes 数据只允许通过只读 importer 迁移。
- **FR-CORE-005 [Approved]**：API、Bridge、Worker 必须可以独立启动、停止和重启。

### 3.2 问鼎 AI

- **FR-AI-001 [Approved]**：默认 Base URL 为 `https://wendingai.future1.us/v1`。
- **FR-AI-002 [Approved]**：默认模型为 `gpt-5.3-codex-spark`。
- **FR-AI-003 [Approved]**：模型优先级为联系人 override > WhatsApp 账号 AI Profile > 全局默认。
- **FR-AI-004 [Approved]**：智能回复、自动翻译、手动翻译、总结均通过统一 AI Provider。
- **FR-AI-005 [Approved]**：AI 请求失败必须返回结构化错误，禁止伪装成模型成功。
- **FR-AI-006 [Approved]**：设置页显示 effective model 及来源层级，但不返回 API key。
- **FR-AI-007 [Approved]**：记录 request ID、模型、延迟、状态与 usage；日志不得包含密钥和完整敏感消息。
- **FR-AI-008 [Approved]**：管理员可在设置页自定义问鼎 AI 全局默认模型并立即热生效；空值回退 `gpt-5.3-codex-spark`。
- **FR-AI-009 [Approved]**：管理员可在设置页新增或替换问鼎 AI API key；密钥必须服务端加密保存，API 只返回 `api_key_configured` 和脱敏提示，不得返回明文。空提交表示保留原密钥，显式清除必须二次确认并写审计日志。
- **FR-AI-010 [Approved]**：数据库内保存的模型和加密密钥覆盖环境变量；数据库无值时回退 `WENDING_AI_*` 环境变量。密钥更新后新的 AI 请求立即使用新配置，无需重启服务。
- **FR-AI-011 [In Progress]**：“我 → 全局 AI 设置”必须提供全局 Provider、模型、密钥、默认提示词、默认回复风格与自动翻译入口；自动翻译对 Legacy/V2 字符串消息 ID 均有效，失败必须显示可重试错误。
- **FR-AI-012 [Approved]**：智能回复必须接受会话级 persona_id；重写器以受控人设 prompt 增强系统指令；返回结果在 `rewrite.persona` 字段返回 `id/name/category/accent`；切换/卸载/未知/插件关闭任一情况都必须立即回退默认策略，不能只改变 UI；不得向第三方加载远程 prompt 或代码。

### 3.3 多 WhatsApp 账号

- **FR-ACC-001 [Approved]**：可在 UI 中创建多个 WhatsApp 账号记录。
- **FR-ACC-002 [Approved]**：每个账号可独立生成 QR、扫码登录并显示实时连接状态。
- **FR-ACC-003 [Approved]**：每个账号拥有独立 socket、session 目录、重连和限速状态。
- **FR-ACC-004 [Approved]**：账号 A 的断线、登出、删除不得影响账号 B。
- **FR-ACC-005 [Approved]**：账号可设置显示名、主账号、AI Profile、自动回复模式和启停状态。
- **FR-ACC-006 [In Progress]**：控制台支持跨平台“全部消息”聚合视图、平台筛选，以及平台下的单账号筛选；例如 `ALL → WA → WA1/WA2/WA3`。
- **FR-ACC-007 [Approved]**：发送区必须锁定当前会话所属账号，禁止跨账号误发。
- **FR-ACC-008 [Approved]**：删除账号凭据必须二次确认；普通停用不删除 session。
- **FR-CHN-001 [Draft]**：账号模型统一支持 WhatsApp、Telegram、Facebook Page Messenger 和 Instagram 专业账号，并以 `platform + connection_type + external_account_id` 标识连接。
- **FR-CHN-002 [Draft]**：Telegram 首选 Business Connected Bots；Bot API 用于机器人/群组；TDLib 仅作为需要完整用户历史与群组能力的高级可选连接。
- **FR-CHN-003 [Draft]**：Facebook 仅支持 Page Messenger，Instagram 仅支持 Business/Creator 专业账号；不支持个人 Facebook Profile Inbox 或 Cookie/浏览器自动化方案。
- **FR-CHN-004 [Draft]**：Meta 账号必须通过 Facebook Login for Business、Business Login for Instagram 或 WhatsApp Embedded Signup 授权；不得收集用户平台密码。
- **FR-CHN-005 [Draft]**：所有平台发送必须经过账号能力和政策网关，强制检查 24 小时窗口、模板/标签、opt-in、速率限制和授权有效性。

### 3.4 会话与消息

- **FR-MSG-001 [Approved]**：会话列表显示账号、联系人、最后消息、时间、真实未读、置顶和静音。
- **FR-MSG-002 [Approved]**：会话支持分页、增量更新和搜索，不允许全库扫描阻塞页面。
- **FR-MSG-003 [Approved]**：消息支持文本、图片、音频、视频和文档基础类型。
- **FR-MSG-004 [Approved]**：出站消息拥有 `queued/sending/sent/delivered/read/failed` 状态。
- **FR-MSG-005 [Approved]**：失败消息保留原文、账号和目标，可安全重试。
- **FR-MSG-006 [Approved]**：入站事件与出站回执必须幂等处理。
- **FR-MSG-007 [Approved]**：查看历史时新消息不得强制滚底；应显示新消息入口。
- **FR-MSG-008 [Approved]**：会话删除默认是业务归档/隐藏；WhatsApp 远端撤回必须依协议能力单独定义。
- **FR-MSG-009 [In Progress]**：当前会话必须按所属数据面增量或全量刷新；V2 会话不得因前端分支短路而停止同步。
- **FR-MSG-010 [In Progress]**：发送必须锁定当前会话所属账号与 Bridge；V2 会话禁止调用 Legacy `/api/reply`，发送成功后必须立即写入独立消息库并返回本地 ID 与平台 ID。

### 3.5 联系人与画像

- **FR-CON-001 [In Progress]**：联系人为独立数据源，不再从会话列表临时推导；通讯录支持跨平台聚合、平台筛选和单账号筛选。删除/隐藏会话只影响聊天列表，不删除或隐藏联系人；从通讯录点击联系人可恢复已有会话或创建空会话。
- **FR-CON-011 [In Progress]**：WhatsApp Adapter 必须同步账号联系人、已有聊天和有界近期历史；联系人/聊天/历史批次按账号隔离且幂等，过滤 status、broadcast、newsletter 和系统 JID，群聊不得污染个人通讯录。
- **FR-CON-012 [In Progress]**：账号连接期望状态以数据库为真源；Bridge/API 重启后必须对 enabled 且期望 connected 的账号执行幂等注册与连接恢复，用户明确 stop/logout 的账号不得自动重连。
- **FR-CON-002 [Approved]**：支持备注、标签、分组、语言、说明和搜索。
- **FR-CON-003 [Approved]**：同一电话号码或远端 ID 在不同平台/账号下是隔离联系人；UI 必须显示所属平台和账号，避免同名误认。
- **FR-CON-013 [Approved]**：联系人显示名优先级固定为“人工备注 → WhatsApp 同步的联系人 display_name / push_name → 会话标题 → 远端 ID”；会话标题不得覆盖已同步联系人名称，联系人无名称时才回退到远端 ID。
- **FR-CON-004 [Approved]**：AI 画像使用结构化字段，Markdown 仅作为展示/导出格式。
- **FR-CON-005 [Approved]**：画像必须采用 Evidence → Claim → Snapshot 三层结构；事实、观察、模型推断和人工输入分别标识，每个 AI Claim 可追溯到消息或总结证据。
- **FR-CON-006 [Approved]**：人工确认、修改或锁定的画像字段优先级高于模型；后台任务不得静默覆盖，冲突只能生成待审核建议。
- **FR-CON-007 [Approved]**：支持联系人级查看、编辑、确认、拒绝、锁定、删除、重新分析和关闭画像/记忆处理。
- **FR-CON-008 [Approved]**：会话按增量游标生成 segment/daily/weekly/rolling 总结，并提取话题、决定、承诺、待办、偏好和关系事件；重复执行必须幂等。
- **FR-CON-009 [Approved]**：AI 回复只加载与当前话题相关且允许使用的记忆、画像和总结；不得使用 rejected、expired、越权或低置信信息。
- **FR-CON-010 [Approved]**：敏感属性默认禁止推断；人格分析只能表达可观察沟通倾向，不得作医学、政治或受保护属性诊断。

### 3.6 插件

- **FR-PLG-001 [Approved]**：插件开关必须在对应 API、AI 服务或 Worker 有真实 gate。
- **FR-PLG-002 [Approved]**：没有 hook 的插件显示为“不可用/待实现”，不能显示“已启用”。
- **FR-PLG-003 [Approved]**：插件支持 global/account 两种作用域。
- **FR-PLG-004 [Approved]**：插件启停写入数据库并产生审计日志。
- **FR-PLG-005 [Approved]**：画像插件必须提供 global/account 配置 Schema、Worker readiness、调度、预算、保留期、最近任务和错误状态；不可用时禁止启用。
- **FR-PLG-006 [Approved]**：批量画像同步支持平台/账号/标签范围、dry-run、只处理 empty/stale、并发与每日预算、暂停、取消、失败重试和逐联系人结果。
- **FR-PLG-007 [Approved]**：系统必须提供受控 AI 人设目录。每项人设只可包含已审计的提示词约束和展示元数据，禁止执行第三方代码、脚本或未验证网络内容；人设支持启停、版本和默认回退；UI 仅展示受控目录元数据，禁止显示任何外部源/仓库信息。
- **FR-PLG-008 [Approved]**：人设可为单个联系人/会话选择，选择必须由服务端保存并真实进入智能回复 Prompt；插件关闭、未知人设或清除选择时必须立即回退默认策略，不能只改变 UI。

### 3.7 定时与群发

- **FR-JOB-001 [Approved]**：定时消息必须由 Worker 到点真实执行。
- **FR-JOB-002 [Approved]**：Worker claim 必须有 lease/幂等保护，防止重复发送。
- **FR-JOB-003 [Approved]**：群发按收件人记录排队、发送、成功、失败和取消状态。
- **FR-JOB-004 [Approved]**：群发必须指定 sender account，并使用账号级限速。
- **FR-JOB-005 [Approved]**：群发支持暂停、取消、失败项重试与进度查询。

### 3.8 前端 UX

- **UX-001 [Implemented]**：移动端优先，保持微信式 cell list、聊天气泡、抽屉和底部导航；≤760px 使用会话列表→聊天窗两级导航，聊天内隐藏底部导航并提供返回键；桌面聊天区采用安静的双栏结构，不使用后台管理式卡片堆叠。
- **UX-009 [In Progress]**：收件箱筛选采用两级模型：一级为 `ALL/平台`，二级为该平台账号；会话行同时展示平台与账号标签。
- **UX-010 [In Progress]**：通讯录按平台与账号聚合，支持平台/账号筛选、搜索和账号身份展示。
- **UX-002 [Approved]**：图标统一使用可验证的 inline SVG 或静态资源，不用功能性 emoji 代替。
- **UX-003 [Approved]**：页面滚动容器明确，不得用全局 `overflow:hidden` 阻断内容滚动。
- **UX-004 [Approved]**：中文输入法组合期间 Enter 不触发发送。
- **UX-005 [Approved]**：聊天页只放当前联系人相关动作；全局配置进入设置/我页。
- **UX-006 [Approved]**：设置移动端使用全屏分级页面，桌面端可使用面板。
- **UX-007 [Approved]**：所有用户可见文案必须进入 i18n，并保持全部语言 key 对齐。
- **UX-008 [Approved]**：支持 safe area、focus-visible、dialog focus trap、aria-live 和 reduced motion。
- **UX-011 [Approved]**：中文是系统默认、未知语言和缺失翻译的最高优先级语言；用户可主动切换英语、泰语或老挝语且无需刷新。任何 V1 受保护功能必须复用统一认证 API 客户端，认证失败必须向用户显示错误，禁止静默降级为空列表或伪装“无数据”。
- **UX-012 [Approved]**：设置在桌面使用左侧分组导航和独立可滚动内容区；移动端使用全屏页面、单行可横滑导航和固定底部操作栏，不能以多行 Tab 网格挤压或遮挡表单内容。主题显式选择必须设置目标主题，不能依赖反转。
- **UX-013 [Approved]**：发现页保持微信式信息架构——保留“我 → 服务/设置”入口，发现页只展示运营概览和受控 AI 人设；插件目录仍统一在“我 → 插件中心”入口，未接通 Worker 的能力以“未接通”状态呈现，不可被启用、不可作为发送目标。定时发送、群发在拥有可靠 Worker 之前不进入发现页或设置 Tab；接口保留并返回 501，使 UI 不能让用户提交。

## 4. 非功能需求

- **NFR-REL-001 [Approved]**：Bridge、API 或 Worker 单独重启不丢已持久化事件和待发任务。
- **NFR-REL-002 [Approved]**：所有外部请求有明确连接/读取超时和有限重试。
- **NFR-PERF-001 [Approved]**：会话和消息查询必须数据库分页并具备必要索引。
- **NFR-PERF-002 [Approved]**：账号状态、任务进度和新消息通过 SSE/WebSocket 或可控增量轮询更新。
- **NFR-OBS-001 [Approved]**：记录账号在线状态、事件积压、发送成功率、AI 延迟、429/5xx 和 Worker 队列深度。
- **NFR-OPS-001 [Approved]**：生产由 systemd 或容器编排管理 API、Bridge、Worker。
- **NFR-OPS-002 [Approved]**：提供 live/readiness health checks。
- **NFR-PORT-001 [Approved]**：开发环境可用 SQLite，生产推荐 PostgreSQL；业务逻辑不得依赖 SQLite 特有行为。

## 5. 安全需求

- **SEC-001 [Approved]**：API key、密码、session token、WhatsApp 凭据不入 Git。
- **SEC-002 [Approved]**：Bridge 只绑定 loopback/Unix socket，并使用内部 token 验证。
- **SEC-003 [Approved]**：Web 鉴权迁移为 HttpOnly Cookie + CSRF，移除默认弱密码。
- **SEC-004 [Approved]**：登录、账号登录/登出、设置变更、发送、群发和插件变更写审计日志。
- **SEC-005 [Approved]**：账号/会话 API 必须做 account scope 校验，避免越权访问。
- **SEC-006 [Approved]**：删除 WhatsApp session 属高危操作，必须显式确认并可审计。

## 6. 完成定义

一个需求只有同时满足以下条件才可标为 `Verified`：

1. SDD 中有明确需求 ID、状态和验收标准；
2. 存在覆盖成功、失败、边界和隔离场景的自动测试；
3. 实现通过相关单测和全量回归；
4. 前端功能通过生产构建；
5. 真实 API/Worker/Bridge 链路已验证；
6. 不存在仅 UI 有按钮、后端无执行路径的伪功能；
7. 更新 CHANGELOG、PROJECT_MEMORY、DECISIONS、TODO；
8. 部署后完成健康、静态资源、关键功能和日志验证。
