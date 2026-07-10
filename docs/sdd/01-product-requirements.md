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

### 3.3 多 WhatsApp 账号

- **FR-ACC-001 [Approved]**：可在 UI 中创建多个 WhatsApp 账号记录。
- **FR-ACC-002 [Approved]**：每个账号可独立生成 QR、扫码登录并显示实时连接状态。
- **FR-ACC-003 [Approved]**：每个账号拥有独立 socket、session 目录、重连和限速状态。
- **FR-ACC-004 [Approved]**：账号 A 的断线、登出、删除不得影响账号 B。
- **FR-ACC-005 [Approved]**：账号可设置显示名、主账号、AI Profile、自动回复模式和启停状态。
- **FR-ACC-006 [Approved]**：控制台支持“全部账号”聚合视图和单账号筛选。
- **FR-ACC-007 [Approved]**：发送区必须锁定当前会话所属账号，禁止跨账号误发。
- **FR-ACC-008 [Approved]**：删除账号凭据必须二次确认；普通停用不删除 session。

### 3.4 会话与消息

- **FR-MSG-001 [Approved]**：会话列表显示账号、联系人、最后消息、时间、真实未读、置顶和静音。
- **FR-MSG-002 [Approved]**：会话支持分页、增量更新和搜索，不允许全库扫描阻塞页面。
- **FR-MSG-003 [Approved]**：消息支持文本、图片、音频、视频和文档基础类型。
- **FR-MSG-004 [Approved]**：出站消息拥有 `queued/sending/sent/delivered/read/failed` 状态。
- **FR-MSG-005 [Approved]**：失败消息保留原文、账号和目标，可安全重试。
- **FR-MSG-006 [Approved]**：入站事件与出站回执必须幂等处理。
- **FR-MSG-007 [Approved]**：查看历史时新消息不得强制滚底；应显示新消息入口。
- **FR-MSG-008 [Approved]**：会话删除默认是业务归档/隐藏；WhatsApp 远端撤回必须依协议能力单独定义。

### 3.5 联系人与画像

- **FR-CON-001 [Approved]**：联系人为独立数据源，不再从会话列表临时推导。
- **FR-CON-002 [Approved]**：支持备注、标签、分组、语言、说明和搜索。
- **FR-CON-003 [Approved]**：同一电话号码在不同 WhatsApp 账号下是隔离联系人。
- **FR-CON-004 [Approved]**：AI 画像使用结构化字段，Markdown 仅作为展示/导出格式。

### 3.6 插件

- **FR-PLG-001 [Approved]**：插件开关必须在对应 API、AI 服务或 Worker 有真实 gate。
- **FR-PLG-002 [Approved]**：没有 hook 的插件显示为“不可用/待实现”，不能显示“已启用”。
- **FR-PLG-003 [Approved]**：插件支持 global/account 两种作用域。
- **FR-PLG-004 [Approved]**：插件启停写入数据库并产生审计日志。

### 3.7 定时与群发

- **FR-JOB-001 [Approved]**：定时消息必须由 Worker 到点真实执行。
- **FR-JOB-002 [Approved]**：Worker claim 必须有 lease/幂等保护，防止重复发送。
- **FR-JOB-003 [Approved]**：群发按收件人记录排队、发送、成功、失败和取消状态。
- **FR-JOB-004 [Approved]**：群发必须指定 sender account，并使用账号级限速。
- **FR-JOB-005 [Approved]**：群发支持暂停、取消、失败项重试与进度查询。

### 3.8 前端 UX

- **UX-001 [Approved]**：移动端优先，保持微信式 cell list、聊天气泡、抽屉和底部导航。
- **UX-002 [Approved]**：图标统一使用可验证的 inline SVG 或静态资源，不用功能性 emoji 代替。
- **UX-003 [Approved]**：页面滚动容器明确，不得用全局 `overflow:hidden` 阻断内容滚动。
- **UX-004 [Approved]**：中文输入法组合期间 Enter 不触发发送。
- **UX-005 [Approved]**：聊天页只放当前联系人相关动作；全局配置进入设置/我页。
- **UX-006 [Approved]**：设置移动端使用全屏分级页面，桌面端可使用面板。
- **UX-007 [Approved]**：所有用户可见文案必须进入 i18n，并保持全部语言 key 对齐。
- **UX-008 [Approved]**：支持 safe area、focus-visible、dialog focus trap、aria-live 和 reduced motion。

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
