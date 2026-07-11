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

- 状态：`Approved`
- 需求：FR-MSG-004~006
- 验收：
  - API 返回 queued，而非提前 sent；
  - Worker 重启后继续 pending 任务；
  - 幂等 key 防重复发送；
  - 状态机和失败重试测试覆盖。

### SDD-P0-06 定时任务真实 Worker

- 状态：`Approved`
- 当前缺陷：现有 `/api/schedule` 只保存配置，不执行。
- 验收：
  - 到点真实发送；
  - 多 Worker 不重复；
  - 可取消；
  - 账号离线时进入可追踪失败/重试状态。

### SDD-P0-07 群发后台任务

- 状态：`Approved`
- 当前缺陷：现有 HTTP handler 同步循环发送。
- 验收：
  - 后台分片执行；
  - 账号级限速和抖动；
  - 进度、暂停、取消、续跑、逐项结果；
  - 重试不重复发送已成功目标。

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
- 本轮进展：聊天、通讯录、发现、我、账号中心已统一使用独立页面壳、滚动容器和移动端安全区；全局 AI 配置保持在“我”页；聊天头部仅保留返回、联系人名称/状态和“…”；Emoji、直发、AI 智能、翻译模式进入输入区折叠面板；双方使用微信式方形头像和左右镜像气泡。
- 剩余内容：
  - “发现”改“工作台”；
  - “我”页进一步只保留操作员和全局设置；
  - 设置移动端全屏分级。

### SDD-P1-05 翻译异步化

- 状态：`Implemented`
- 已实现：插件开关、消息设置和 AI Provider 形成统一有效门禁；运行时加密配置热生效；Legacy 整数 ID 与 V2 UUID 均可翻译；失败向 UI 返回可操作错误，不再静默或把原文伪装成译文；前端按 message ID 记录 in-flight 请求，避免轮询和状态更新期间重复翻译；译文内嵌所属气泡以保持稳定布局。
- 已验证：真实 Provider 老挝语→中文探针成功，Provider 配置与翻译 Worker 使用同一运行时设置。
- 剩余验收：消息读取已改为 cache-only，不再同步触发 Provider；本轮已修复单客户端轮询、V2刷新和失败重试。仍需将翻译缓存迁移数据库 revision/event cursor，并提供 SSE/WebSocket 跨客户端实时更新，才能进入 `Verified`。

### SDD-P1-06 插件完整接线

- 状态：`In Progress`
- 已实现：`auto_translate` 同时控制读取时翻译和手动翻译 API；`quick_reply` 控制 AI 预览；插件目录显示 hook 和运行状态；无可靠 Worker/Hook 的定时、群发、TTS、媒体、自动标签和跟进插件返回 `available=false`，前端禁用开关且后端拒绝启用。
- 剩余缺陷：完成定时和群发可靠 Worker 后，再逐项开放对应插件。
- 验收：每个 available 插件有真实 API/worker gate；无 hook 时 `available=false`。

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

## 4. P2：UX、视觉和工程质量

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

- focus-visible；
- dialog focus trap；
- aria-live；
- 键盘操作；
- reduced motion；
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
