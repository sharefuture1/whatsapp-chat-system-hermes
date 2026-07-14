## 2026-07-14：P0-09 自动回复可靠性补全（执行前竞态取消 + lease recovery + backoff）

- `auto_reply.py`：入站自动回复 enqueue 现在显式过滤 `message_type=system`，并将 `account_id` 纳入 idempotency key / input hash 语义，降低跨账号与策略混淆风险。
- `auto_reply_worker.py`：执行前二次校验已补齐：再次检查联系人 `auto_reply_enabled`、过滤 system message、若该入站消息之后已存在人工 outbound 回复则直接取消 job，避免客服与 AI 抢答。
- worker 现每 30 秒自动执行 `recover_expired_leases(...)`，health 增加 `recovered_leases`；失败重试从固定 30 秒升级为指数退避 + jitter（上限 300 秒）。
- 质量门禁：focused pytest 45 passed；全量 Python 243 passed；automation health / api health 200。

## 2026-07-14：微信式设置全屏二级页（SDD-P1-11，完成真实接线）

- 新增 `web/src/components/SettingsPage.jsx`：全屏微信式设置主页，5 个 cell 入口路由到子页（账号与安全/AI 助手/聊天与翻译/通用/关于），取代原 5-tab `SettingsPanel` 模态。
- `App.jsx` 引入 `settingsView` state：`null`（未进入）/ `'main'`（设置主页）/ `'security' | 'ai' | 'chat' | 'general' | 'about'`（子页），由 MePage 入口触发。
- `MePage` 顶部 hero 重构：显示真实登录用户名、当前角色（管理员/操作员）、服务状态/自动翻译/在线账号 3 个状态 pill，右上角 QR 入口按钮跳到账号中心。
- 每个 cell row 升级为微信 cell 风格：左图标 + 中标题副标题 + 右值/箭头；非管理员隐藏「用户管理」行；自动翻译行使用 settings 入口而非 AI 入口。
- CSS：`.wx-settings-page` 全屏壳、`.wx-page-header-back` 返回按钮、`.wx-me-qr-btn` QR 入口、`.wx-setting-row:focus-visible` 键盘可达、暗色模式 pill 配色。
- i18n：新增 23 个 key（settingsSecurity、settingsAi、settingsChat、settingsGeneral、settingsAbout、roleAdmin、roleOperator、configured、appName、version、serviceStatus、default、chat、changePassword、settingsAiAdminHint、settingsAiOperatorHint 等），全部覆盖 en/zh/th/lo。
- 质量门禁：i18n 一致性测试 2 passed、Python 243 passed、Vite build PASS、production health 200。
- 已提交：`95fcdb6` 已推送 main。

## 2026-07-14：继续全面优化：Standalone 插件 V1、AI runtime 解耦与多语言修复

- 修复 `PluginCenterPage`：插件列表、toggle、disable 全部切换到 `/api/v1/plugins`；原 `/api/plugins` 在 Standalone 下会返回前端 HTML。
- 新增 `src/whatsapp_chat_system/api/v1/plugins.py`：真实插件 catalog、`available/unavailable_reason/status_when_on/hooks`、可用插件持久化开关、不可用插件结构化 409。
- Standalone AI 配置不再从 Legacy `web_api` 导入；新增独立 `StandaloneAISettingsManager`，翻译 Worker 读取业务库加密 API key。
- 修复 legacy auth → users 迁移会覆盖原密码的问题：迁移时验证并保留现有 auth 记录。
- 修复四语言用户管理/AI 测试缺失 key与重复 key，补充插件 API 回归测试。
- 质量门禁：Python `241 passed`、Web `87 passed`、Bridge `74 passed`、Bridge lint PASS、Vite build PASS。


## 2026-07-14：24x7 AI 自动回复工程化规格建立

- 当前已完成 AI Worker 的第一版闭环：入站事件按策略创建 `analysis_jobs`，Standalone Worker 负责 claim/AI/complete 或 retry/dead，成功后幂等写入 Outbox；`/api/v1/automation/health` 已在生产返回 200。尚未达到 Verified：限速/熔断、管理员策略 API、真实 WhatsApp 收发与连续 24 小时测试仍待完成。
- 新增 `SDD-P0-09` 与实施计划 `docs/plans/2026-07-14-engineering-phase2-auto-reply.md`。
- 明确自动回复必须满足：账号/会话/联系人策略、幂等、AI Job lease/retry/dead、Outbox 回执、限速/预算/熔断、管理员暂停、health API 和真实 24 小时验收。


- 新增 `docs/plans/2026-07-14-engineering-phase1-data-layer.md`，冻结数据层和性能重构边界。
- 更新 `docs/sdd/05-optimization-backlog.md`：明确 Phase 1 数据层、Phase 2 SSE/cursor、Phase 3 翻译/AI Job、Phase 4 媒体/可观测性。
- 当前重点从继续堆 UI 转为统一 API client、请求预算、状态真源和可验证的同步链路。


### 前端 UI 优化

- `SettingsPanel.jsx`：AI 设置页新增**测试连接**按钮（左侧 ghost 按钮）和结果反馈区
  - 测试时用表单当前值（未保存也可用），点击后显示绿色 ✓ 连接成功或红色 ✗ 错误信息
  - 三个字段（API Key / 模型 / Base URL）任一改动自动清除上次测试结果
  - 按钮状态：`disabled` + "测试中…"防止重复点击
- 按钮组改为左测试右保存，间距 8px，保存按钮右侧贴齐
- i18n 新增 `testConnection / testing / connectionSuccess / connectionFailed`（中/英）

### 后端新端点

- `POST /api/v1/ai/test`：直接调用 `WendingAIProvider` 验证凭据，返回 `{ok, message}`
  - 优先使用表单传入值，其次读 DB 加密存储的 key，再其次读 `runtime.ai_settings` 默认值
  - 生产验证：`{"ok":true,"message":"Connected — model: gpt-5.3-codex-spark"}` → 200 ✅

### 翻译端点修复

- `api/v1/messages.py`（新建）：`POST /api/v1/messages/{message_id}/translate`，前缀 `/api/v1/messages`
  - 匹配前端旧路径 `/messages/${msg.message_id}/translate`，无需改前端 JS
  - 解决旧路径被中间件拦截返回 `legacy_api_disabled` (410) 的问题
- `standalone_api.py`：注入 `app.state.runtime = runtime`；注册 messages router

### 验证结果

- `/api/health` → 200 ✅
- `/api/v1/ai/test` → 200 `{"ok":true,"message":"Connected — model: gpt-5.3-codex-spark"}` ✅
- `POST /api/v1/users/register`（admin session）→ 201 ✅
- 新 bundle：`index-BqseTvKJ.js`（308.87 KB）/ `index-CyWC_Vl7.css`（76.16 KB）

## 2026-07-14：性能与前端可访问性优化 + 密码入库整改

- AI Provider：`WendingAIProvider` 默认 Session 改为实例级持久复用（懒加载；`close()` 释放；注入 Session 生命周期归调用方），AI 翻译/重写不再每次调用重建 TCP+TLS 连接，重试共享同一连接池。
- 数据库：`create_engine` 对非 SQLite（生产 PostgreSQL）启用 `pool_pre_ping` / `pool_recycle=1800` / `pool_size=10` / `max_overflow=20`，防止陈旧连接引发间歇性失败；SQLite 行为不变。
- 前端性能：`ChatList`、`TabBar` memo 化；App 层将 `contactProfileMap`、`chatListAccounts` 与平台/账号切换、Tab 切换、打开设置回调用 useMemo/useCallback 稳定化，工作台轮询与无关 state 变化不再触发整列表重渲染。
- 可访问性（SDD-P2-04 部分落地）：全局键盘 `:focus-visible` 焦点环；`prefers-reduced-motion` 下关闭装饰性过渡/动画。
- 安全整改：删除误提交的 `web/src/i18n.js.bak`；`.gitignore` 新增 `*.bak`。
- 门禁：Python `238 passed`（+4）、Web `87 passed`（+4）+ Vite build、Bridge `74 passed` + lint、changed-files ruff check/format 与 `git diff --check` 全部通过。
- 计划：`docs/plans/2026-07-14-perf-ui-optimization.md`。

## 2026-07-14：修复 auth 记录缺失导致全员 401（hotfix）

- `web-settings.json` 缺少 `auth` 字段（无 `scheme`/`salt`/`hash`），导致所有认证请求返回 401，前端误报"AI 翻译失败"。
- 重建密码记录（scheme: pbkdf2_sha256），重启后登录和 AI 翻译恢复正常。
- **注意**：下次 systemd 升级若使用 EnvFile 中的 `CHAT_SYSTEM_BOOTSTRAP_PASSWORD`，服务重启后密码不变（持久化在 `web-settings.json`）；若直接删除 `web-settings.json`，则需要 EnvFile 中存在 ≥12 字符的 bootstrap password。

## 2026-07-13：Standalone 可靠性分支合并（Implemented，待独立生产切流验收）

- 合并 `fix/standalone-reliability-ux-20260713`：Standalone V1 完成可靠 Outbox Dispatcher、lease ownership 防旧 Worker 覆盖、Bridge idempotency key 与 receipt 持久化/恢复。
- Standalone 新增 `/api/v1/schedule`、`/api/v1/broadcast`、`/api/v1/outbox`；写入统一返回 `202 queued`，定时通过 `available_at` 执行，群发按目标拆分 Outbox 并返回逐项 queued/rejected。
- 安全与可靠性：Standalone CORS 显式 origin、登录限流、AI runtime retry 覆盖、历史消息稳定 cursor 分页、迁移期前端只对已知 Legacy 410 安全降级。
- 质量门禁：新增 GitHub Actions Python/Web/Bridge/whitespace gates；合并后 Python `234 passed`、Web `83 passed` + Vite build、Bridge `74 passed` + lint、`git diff --check` 均通过。
- 未完成：独立 systemd 切流、真实 WhatsApp 账号 Outbox 收发/回执/重启恢复、多 Worker claim、群发限速/暂停/续跑；这些前不得标记 Verified。

## 2026-07-13：插件中心可观察性与任务中心落地（Implemented）

- `PLUGIN_CATALOG` 升级为带 `available / unavailable_reason / status_when_on / hooks` 的真值：
  - 可用：`auto_translate / quick_reply / persona_styles / memory / analytics`
  - 不可用：`schedule / broadcast / voice_tts / media_pack / auto_tag / followup`，全部带明确原因（指向 SDD-P0-06/07 等）。
- `/api/plugins` 直接返回上述元数据；前端不可用插件的开关自动禁用并展示原因。
- `/api/dashboard.stats` 扩展为 `unread_messages / pending_replies / sent_messages / avg_response_seconds`，统计插件有真数据。
- 新增前端 `SchedulerCenterPage` 与 `BroadcastCenterPage`：列出当前任务，提供创建向导（Worker 未接通前会以 toast 提示）。
- 插件中心定时/群发卡片显示“打开任务中心”按钮，跳转到对应 CenterPage。
- i18n：四语新增 `schedulerTitle / broadcastTitle / pluginUnavailableReason / pluginHookEmpty / openToolCenter` 等。
- 验证：Python `225 passed`、Web `79 passed`、Vite build、`git diff --check` 通过；systemd 重启后 `/api/health` 200，公网与本地均命中 `assets/index-BSMu_Kn5.js` / `index-BU2zSI7R.css`。

## 2026-07-13：发现页与设置页微信化 + 定时/群发降级（Implemented）

- 新增 UX-013：发现页只保留运营概览与受控 AI 人设；插件目录迁到 Me → 插件中心；定时发送、群发在可靠 Worker 落地前从 UI 中移除，API 写入端改为返回 `503 scheduler_not_connected` / `503 broadcast_not_connected`，不再让用户提交。
- 重构 SettingsPanel：从六个高密度 Tab 收敛为 5 个核心 Tab（回复策略 / 全局 AI / 界面 / 账号中心 / 安全），全部走 i18n key；主题按钮调用显式 `setTheme('light'|'dark')`；移动端沿用 UX-012 的单行横滑导航与底部固定操作栏。
- 新增 `components/PluginCenterPage.jsx`：独立的“插件中心”全屏页面，含搜索、分组、状态、不可用原因展示；Me 页新增入口。
- Me 页整理为微信式分组：账号与连接 / 全局 AI / 服务（插件中心、设置）/ 偏好（语言、主题）/ 退出登录。
- i18n：新增 `servicesTitle / preferencesTitle / apiKey / apiKeyKeep / apiKeyInput / apiKeyCurrent` 四语对齐；旧 `pluginCenter / pluginsEnabled` 中文重复键修复。
- 验证：Python `223 passed`、Web `76 passed`、Vite build、`git diff --check` 通过；systemd 重启后 `/api/health` 200，公网与本地均命中 `assets/index-yMpubfk7.js` / `index-BU2zSI7R.css`。

## 2026-07-13：设置页结构与移动端布局收敛（Implemented）

- 新增 UX-012：桌面设置采用侧栏+独立内容滚动；移动端为全屏、单行横滑分段导航、独立滚动表单与固定底部操作栏，避免六个 Tab 网格挤压页面。
- 修复主题按钮：浅色/深色现在调用 `setTheme('light'|'dark')` 精确选择，不再错误地通过无参反转造成点击目标主题却变成另一主题。
- 设置导航移除硬编码英文/中文混合描述，改用 i18n key；未知语言 setter 也回退中文。
- 验证：Python `223 passed`、Web `73 passed`、Vite build、`git diff --check` 通过；systemd 重启后 `/api/health` 200，公网与本地资源一致：`index-BKv2NUGm.js` / `index-BU2zSI7R.css`。

## 2026-07-13：中文全量文案与 WhatsApp 联系人姓名优先级（Implemented）

- 修复中文 locale 中遗留的英文运营、插件、联系人、定时与群发文案；新增静态回归，禁止中文用户可见值退化为未翻译英文（协议/产品专有名词除外）。
- 新增 FR-CON-013：显示名固定遵循“人工备注 → WhatsApp 同步名称 → 会话标题 → 远端 ID”。V1 会话 API 已调整为优先 `Contact.display_name`，不会再由聊天标题压过对方在 WhatsApp 的原始名称。
- 真实库抽查确认现有联系人的 `display_name=future`、`remark=null`，渲染将使用 `future` 而非低优先级标题/JID。
- 验证：Python `223 passed`、Web `72 passed`、Vite build、`git diff --check` 通过；systemd 重启后 `/api/health` 200，本地与公网均命中 `assets/index-DgvLmKLK.js`（309300 bytes）。

## 2026-07-13：账号加载故障恢复（Legacy 兼容服务）

- 根因：前一轮手工重启时没有加载 `/etc/whatsapp-chat-system.env`，Legacy Web API 因此退回空默认 SQLite；`/api/v1/accounts` 查询缺少 `whatsapp_accounts` 表并返回 500，前端显示“账号加载失败”。
- 已将 systemd 服务恢复为 Legacy 兼容启动路径，并明确加载原有环境文件；服务当前 active，实际独立库 `whatsapp_standalone.db` 的账号 Repository 可读取 1 个 online 账号。
- 验证：`/api/health` 200，公网 `assets/index-CjMgNbWo.js` 200（309238 bytes）。Bridge V2 的连接/内部事件仍是迁移期独立问题，不把它误报为账号目录加载失败。

## 2026-07-13：人设目录认证修复与中文优先语言策略（Implemented）

- 根因修复：`personas.js` 不再直接匿名 `fetch` V1 人设接口，而是统一经 `api` 客户端携带登录 session token；401/5xx 不再静默降级为空人设目录，前端会显示实际加载错误。
- 受控人设 `tong-jincheng` 在 UI 明确命名为“童锦程·直球关系顾问”；它是本地审计的通用关系沟通风格，不冒充或模仿真人，仍不显示/下载第三方源。
- 新增 UX-011：中文成为首次访问默认语言、未知语言及缺失 key 的最高优先级回退；语言存储 key 升级为 `chat-system-language-v2`，使既有英文缓存不再覆盖中文默认。用户主动选择英语/泰语/老挝语后仍会持久化并实时生效。
- V1 人设认证、童锦程可见性、401 不静默隐藏和中文优先策略均新增回归覆盖。
- 验证：Python `222 passed`、Web `71 passed`、Vite build、`git diff --check` 通过；Legacy 8792 重启后 `/api/health` 200，`assets/index-CjMgNbWo.js` 200（309238 bytes），公网同资源一致。

## 2026-07-13：人设预览与 Legacy V1 契约闭环（Implemented，待真实账号验收）

- Legacy `build_app` 已实际注册 V1 personas router，并补齐真实登录后的列表/分配回归；未认证请求固定返回 401，不再以 404 或跳过测试掩盖路由缺失。
- 智能/翻译模式在输入工具面板提供真实“预览”操作：仅调用 Legacy `/api/reply` 的 `preview_only=true`，不会发送 WhatsApp 消息；预览响应现包含安全的人设展示元数据，便于确认当前联系人人设已生效。
- `App → ChatPane` 已透传 `previewOnly` 选项，预览不触发发送 busy 状态、全局刷新或错误 toast；Standalone 会话暂不伪装支持预览，会明确失败直到其独立 preview API 落地。
- 清除了 DiscoverPage 未使用的人设启停 API import；恢复原先被跳过的预览契约测试。
- 验证：Python `222 passed`、Web `70 passed`、Vite build、`git diff --check` 通过。生产尚未切流，真实 WhatsApp/Provider 验收仍待完成。

## 2026-07-12：受控 AI 人设 P0（Implemented，未切流）

- 新增 `src/whatsapp_chat_system/api/v1/personas.py`：`GET /api/v1/personas`、`PUT /api/v1/personas/{persona_id}/enable`、`PUT /api/v1/contacts/{contact_id}/persona`；默认人设不可关闭；未知人设 404；清空选择写入 `default`。
- 受控人设目录仅含静态审计的 `default / tong-jincheng / professional-service / mature-uncle`，prompt 不下发到客户端；前端 UI 禁止显示任何外部源/仓库信息。
- `router.prepare_reply` 与 admin_router 都读 `web_settings.contact_profiles[contact_id].persona_id` 并透传到 rewriter；切换/卸载/未知/插件关闭任一情况均回退默认策略。
- V1 API 同时在 standalone `_build_standalone_app` 与 legacy `build_app` 注册，开发与生产不依赖 Hermes。
- 前端 `web/src/personas.js` 客户端封装 V1 调用；`ChatPane` 头部 `…` → AI 人设 picker 真实接通；`DiscoverPage` "AI 人设"分类展示受控目录。
- PC 端 `.wx-sidebar-nav` 补齐 `display:flex`、宽度从 64px 加到 72px、深色阴影、按钮更大尺寸，桌面 768px+ 真正可见。
- 实施计划：`docs/plans/2026-07-12-persona-plugins.md`；测试 9 个 Python + 4 个 Web 全部 GREEN。
- 验证：Python `219 passed`、Web `69 passed (1 skipped)`、Vite build、`git diff --check` 通过。未触碰生产 `/etc`、未重启服务、未切流。

## 2026-07-12：Standalone API 运行时脱离 Hermes（Implemented，未切流）

- 新增 `standalone_api.py` 与独立 `runtime.py`；`whatsapp-chat-system serve` 不再加载 Legacy `web_api`、Hermes profile、`state.db`、AdminRouter 或 Legacy Bridge。
- standalone 启动只接受独立 `CHAT_SYSTEM_RUNTIME_DIR`、`DATABASE_URL`、`WHATSAPP_BRIDGE_INTERNAL_TOKEN`；数据库必须已迁移到当前 Alembic head，否则启动拒绝 ready。
- 首次初始化要求至少 12 字符 bootstrap password；已保存有效 PBKDF2 认证记录后重启不再依赖该环境变量。runtime 设置采用 0700/0600 权限与 fsync + replace 原子写入，坏配置 fail-closed。
- Legacy `/api` 与 `/api/*` 在 standalone 下明确返回 `410 legacy_api_disabled`；V1 继续受 session 鉴权。内部事件在 body 校验前验证 token，且统一返回结构化 validation error；短路响应也带 `X-Request-ID`。
- 独立 systemd/迁移合同及 `docs/DEPLOYMENT.md` 已同步；旧生产脚本已硬阻断，不能用于 standalone 切换。
- 验证：Python `203 passed`、Vite build、`git diff --check` 通过；双审查最终 **APPROVED**。未修改生产服务、未执行数据迁移、未进行 WhatsApp 真实收发或切流。

## 2026-07-12：插件目录与四语言可靠性

- 新增 `docs/plans/2026-07-12-plugin-i18n-reliability.md`，落实 SDD-P1-06 的插件可用性、四语言契约与 Worker 边界。
- 修复 `i18n.js` 的重复 key 与 Lao `searchPlaceholder` 漏项；四个 locale 现有完全相同且无重复的 key 集合。`t()` 改用 `??`，不再错误吞掉有效空值。
- Discover/Tools 插件目录现具备：本地化分类、可用/不可用状态、不可用 Worker 原因、禁用开关、隐藏不真实删除动作、busy/错误/空状态和刷新 guard。
- 新增 `web/tests/pluginI18nReliability.test.js` 作为四语言/插件目录静态回归契约。
- 修复与本轮无关但阻塞全量门禁的测试时钟漂移：job repository 测试为固定过去的 `now` 传入 `available_at=now`，保持生产“入队即按实际当前时间可用”的行为不变。
- 验证：Web 契约 3/3，Vite build 通过，Python 183 passed（1 个现有依赖弃用 warning）。

## 2026-07-11：修复同步事件 occurrence 身份冲突

- 同步联系人、聊天和历史批次改为在每次 Baileys handler 调用时生成 occurrence nonce；事件身份包含 occurrence、类型、chunk index 与 canonical content hash。
- 两次内容完全相同的 `contacts.upsert` 不再复用 `event_id`；同一次 handler 的多个 chunk 保持唯一。
- 重放语义保持在 FileSpool：已落盘 envelope 原样保留 `event_id + sequence`，Receiver 幂等/identity conflict 保护不变。
- 删除“跨 occurrence stable replay”的误导测试，新增真实 FileSpool 回归覆盖。

## 2026-07-11：会话删除与通讯录生命周期分离

- Legacy 新增 `/api/contacts`，复用联系人摘要但保留被 `chat_ops.deleted` 隐藏的联系人并返回 `conversation_deleted`；`/api/conversations` 原过滤不变。
- Standalone 新增会话软删除和联系人 ensure/restore API；只更新 `deleted_at`，Contact、Message 和历史均保留。
- 前端通讯录独立读取 Legacy contacts；隐藏 Legacy 会话点击时 restore，Standalone 空会话联系人点击时 ensure，再按 `conversation_key` 选中聊天。
- 删除按 conversation source 分流：Legacy 裸 JID，Standalone conversation UUID；ContactsPage 不再禁用无 conversation_id 联系人。
- 严格 TDD：保存真实 RED；最终 Python `179 passed`、Web `56 passed`、Vite build 和 `git diff --check` 通过。

## 2026-07-11：AI 自动回复与翻译网页同步修复

- 根因一：Legacy 同会话增量请求使用 latest-request-wins，慢响应会被下一轮刷新废弃，出现后端 200 但游标和 React 均不推进。
- 根因二：delta GET 同步生成缺失译文，放大慢请求竞态；翻译旁路缓存不改变消息 ID，旧消息字段变更无法由 `after_id` 表达。
- 前端新增同会话 single-flight/coalesced delta scheduler；会话切换仍拒绝旧响应，补跑消费最新 callback。
- 消息 merge 改为同 ID upsert，并准确对账 optimistic delivery 状态；新增计数只统计真正插入的唯一 ID。
- V2 刷新在服务端没有有效翻译元数据或仅返回 `lang=Unknown` 时保留本地译文；有效服务端元数据仍覆盖本地。
- 翻译失败使用 30 秒有界重试，并同步更新 worker ref，避免 React commit 竞态导致立即热循环。
- Legacy delta API 改为 cache-only attach，缺失译文不再在 GET 请求内调用 Provider；已有缓存仍正常返回。
- 严格 TDD：保存后端真实 RED；Web 新增同步、upsert、计数、重试和 scheduler 回归测试。
- 最终独立审查：**APPROVED**。
- 验证：Python `173 passed`、Web `52 passed` + Vite build、Bridge `63 passed` + lint、`git diff --check` 全部通过。

## 2026-07-11：AnalysisJobRepository 高并发审查阻断修复

- PostgreSQL/SQLite 时间边界分离；claim/recovery PostgreSQL 查询均使用 aware UTC 和 `FOR UPDATE SKIP LOCKED`，支持账号及单任务预算过滤。
- global claim 的 per-account active count 进入候选 SQL，已满账号不再阻塞其他账号；claim 同时排除 cancelled/terminal parent。
- parent cancel 与 child transition 统一先锁 parent row；取消后禁止 enqueue，过期 leased child recovery 直接 cancelled，且 parent statuses 批量加载避免 N+1。
- committed wrapper 在 commit 前构造纯 DTO，commit 后直接返回，不再 expunge。
- claim CAS 冲突改为有界循环；worker start/heartbeat/complete/fail 显式 account scope，complete 将 canonical input hash 放入同一 UPDATE CAS。
- 补齐所有公开参数、进度和 immutable idempotency identity 校验；增加 enqueue/claim backpressure。
- parent cancel 同 savepoint 传播 pending/retry child；claimed/running child 不强抢 lease，但 parent cancelled 后 worker 结果拒绝。
- recovery 消除逐行额外 SELECT；新增 account 分片和精确 expiry 边界。
- 新增 `claim_next_committed` 短事务入口和不可变 `JobLease` DTO；保存 RED 摘要。
- 验证：AI focused 五套 `50 passed`；最终独立规格/并发质量审查 **APPROVED**；全量 Python `171 passed`、Web `39 passed` + Vite build、Bridge `63 passed` + lint、`git diff --check` 全部通过。
- 当前状态为 **Implemented**：Repository 和 committed claim 边界已经可供 Worker 接线，但尚未部署真实 Summary/Profile Worker，因此不标记 Verified。

## 2026-07-11：AI 关系智能 P0 数据层完成（Implemented）

- `FR-CON-005..010`、`FR-PLG-005..006` 已批准；多平台 `FR-CHN-*` 仍保持 Draft。
- 新增 Alembic `0004_ai_relationship_intelligence` 和 7 个核心实体：会话片段、总结、Claim、Evidence、Snapshot、Memory、AnalysisJob。
- `Contact.profile_revision` 提供联系人级单调修订号；Snapshot 保存精确 `source_claim_versions` 和 `source_profile_revision`，可追溯并阻止陈旧发布。
- 画像 Repository 强制 account/contact/conversation scope，消息/总结证据必须真实存在且同 scope。
- Claim 创建、Evidence、revision CAS、状态转换和 Snapshot current 切换均在 savepoint 内原子执行；冲突后外层 Session 仍可安全查询、重试或提交。
- Worker 不得转换任何人工锁定 Claim；Snapshot 优先人工锁定 accepted Claim，排除 restricted 和已过期内容。
- AnalysisJob 契约包含幂等键、优先级、lease、重试、预算、父子任务、进度及 lease recovery 索引；PostgreSQL Worker 后续使用 `FOR UPDATE SKIP LOCKED`。
- 严格 TDD：契约测试先 `6 failed`，模型首次 RED 为缺少模型 ImportError，Repository 首次 RED 为模块不存在；审查发现的原子性、scope、锁和并发问题均增加回归测试后修复。
- 最终独立规格/质量审查：APPROVED。
- 验证：Python `155 passed`、Web `39 passed` + Vite build、Bridge `63 passed` + lint、`git diff --check` 全部通过。
- 当前状态为 **Implemented**：尚未接 Summary/Profile Worker、API 和前端，因此未标记 Verified，生产服务无需切换到新表。

## 2026-07-11：新增 AI 关系智能与多平台账号目标架构

- 新增 `docs/sdd/08-ai-relationship-and-multichannel.md`，定义会话总结、长期记忆、人物画像、拟人回复、插件批处理和多平台 Adapter 架构。
- 新增 Draft 需求：`FR-CON-005..010`、`FR-PLG-005..006`、`FR-CHN-001..005`；当前仅完成规格设计，不宣称生产实现。
- 画像采用 Evidence → Claim → Snapshot，区分明确事实、观察、模型推断和人工输入；每条 AI Claim 可追溯证据，人工锁定不可被 Worker 覆盖。
- 设计 `conversation_summary`、`contact_profile_ai`、`bulk_profile_sync` 三个真实插件，要求配置 Schema、Worker readiness、预算、dry-run、暂停/取消/重试和逐项结果。
- 联系人详情规划为概览/画像/记忆/总结/AI策略五 Tab；聊天页只保留画像状态、轻量入口和回复解释。
- Telegram 推荐 Business Connected Bots → Bot API → TDLib 高级可选；Meta 推荐 Facebook Page Messenger、Instagram 专业账号和 WhatsApp Cloud API 官方授权。
- 明确个人 Facebook Profile Inbox、Cookie/浏览器自动化、Telegram 批量 userbot 不进入正式架构。
- 新增 P0 实施计划 `docs/plans/2026-07-11-ai-relationship-intelligence-p0.md`。

## 2026-07-11：前端轮询、翻译调度与发送对账性能优化

- 关联规格：`NFR-PERF-002`、`NFR-REL-002`、`SDD-P1-05`。
- Workspace 与账号刷新增加 single-flight，同一数据源已有请求时复用 Promise；清理使用显式成功/失败分支，避免 `finally()` 派生未处理 rejection。
- 固定 `setInterval` 改为请求结束后 `setTimeout` 调度；hidden tab 清除定时器，visible 后由唯一 loop owner 恢复一次，慢网和频繁切换不再累积并行轮询链。
- 自动翻译改为单 worker 串行批处理，每批最多 6 条；同批失败消息不立即重复请求，剩余任务主动续批。
- 会话切换、组件清理或关闭自动翻译时 Abort 当前翻译请求，并以 generation 校验阻止旧响应更新新会话。
- 发送成功继续使用服务端真实 local/platform ID 就地更新乐观消息，移除 450ms 后额外全量聊天刷新。
- 新增 `web/tests/performanceScheduling.test.js`，同步更新临时消息与自动翻译源码契约测试。
- 验证：Web `39 passed`、Python `129 passed`、Bridge `63 passed`、Bridge lint、Vite build、`git diff --check` 全部通过。
- 公网 Chromium：390×844 与 1440×900 均 HTTP 200、无控制台错误、`scrollWidth === clientWidth`；生产资源为 `index-CPzFRVjQ.js` / `index-n1Ei7oEG.css`。

## 2026-07-10：微信式移动两级导航与发送状态可靠性修复

- 关联规格：`UX-001`、`UX-005`、`UX-006`、`UX-007`、`FR-MSG-001`、`FR-MSG-002`、`FR-MSG-007`、`FR-MSG-008`。
- 手机 Chats 改为显式两级导航：无 `selectedId` 显示全屏列表，选中后显示聊天；聊天隐藏 TabBar，返回清空选择；桌面保持双栏。
- 删除工作区刷新时自动选首会话的行为，确保手机返回列表不会被下一次轮询重新推进聊天。
- 乐观消息 `tmp-*`、pending、failed 不进入翻译链；回复成功以真实 ID 替换临时 ID，避免 `/api/messages/tmp-*/translate` 422。
- 抽取 `mergeFreshMessages`，服务端刷新按 `role+content` 保留本地 `sent` 标记，并保留尚未被服务端确认的乐观消息。
- 置顶项从普通列表排除；未读改第二行纯红点，时间保留第一行；去除未读数字语义和消息总数药丸。
- 气泡时间统一 HH:MM，同发送方 5 分钟内仅末条显示；相同原文译文不渲染，隐藏翻译操作仅 hover/激活时可见。
- textarea 使用 `scrollHeight` 自动增高到 140px；回复模式改为直发/智能/翻译三选一；手机头部为返回+标题+置顶+更多，设置弹窗全屏。
- 平台账号设置入口改为真实账号中心，底层 channel 路径/目标进入高级折叠；操作员头像改为语言无关 SVG。
- 新增 `web/tests/mobileWechatUx.test.js` 和消息合并单元测试。
- 浏览器验收：390×844 列表→聊天→返回状态正确、无横向溢出、textarea 高度 140px；1440×900 双栏、左右气泡和置顶去重正确。
- 验证：Web 35 passed；Python 129 passed；Bridge 63 passed；Bridge lint 通过；Vite build 通过。
- 生产资源：`index-DRPbZjTf.js` / `index-n1Ei7oEG.css`，本机与公网一致。

## 2026-07-10：修复聊天页闪烁并重构微信式消息布局

- 关联规格：`FR-MSG-002`、`FR-MSG-007`、`UX-001`、`UX-005`、`UX-008`、`SDD-P1-05`、`SDD-P2-01`、`SDD-P2-06`。
- 真实复现：移动端 390×844 连续采样时，修复前消息数在 `0/80`、骨架在 `true/false`、内容高度在 `432/13322` 间周期切换；15 秒产生 52 个 API 响应、6 次 settings 请求和 7 次消息详情请求。
- 根因一：账号 3 秒轮询无条件创建新数组，导致 `fetchConversationsPage`/`refreshWorkspace` callback 重建及初始化 effect 重跑。
- 根因二：ChatPane 初始加载依赖整个 `uiSettings` 对象，设置刷新即清空消息、显示骨架、重载和强制滚底。
- 根因三：自动翻译 effect 在消息更新期间可能对同一条未完成消息重复发起请求。
- 稳定性修复：账号列表语义未变化时保留旧引用；账号当前值改由 ref 提供给稳定 callback；ChatPane 以稳定 `conversationKey` 与 `defaultMode` 标量控制初始化；翻译增加 message-id in-flight Set。
- 微信式布局：头部收敛为返回、居中联系人/状态和单一“…”；移除头部头像与双工具按钮；双方均显示 40px 方形头像和镜像气泡；译文放入所属气泡并使用弱分隔线；输入区采用表情/输入/加号结构，AI 模式和快捷表情进入折叠面板；去除点阵聊天背景。
- TDD：新增 `web/tests/chatStabilityLayout.test.js`，覆盖稳定轮询引用、稳定 callback、稳定会话 identity、单一头部入口、翻译 in-flight 去重、译文归属和双方头像。
- 浏览器验收：修复后首次加载完成的后续 23 个样本均保持 80 条消息、固定容器高度和 scrollTop；settings 请求从 6 降至 1；无控制台错误；390×844 `scrollWidth=390`。
- 验证：Python `129 passed`，Web `22 passed`，Bridge `63 passed` + lint，Vite build 通过，FastAPI health 200。
- 生产资源：`index-PRO4Ip4M.js` / `index-BuimO47C.css`，本机与公网一致。

## 2026-07-10：修复全站滚动/响应式与自动翻译真实 AI 链路

- 关联规格：`SDD-P1-04`、`SDD-P1-05`、`SDD-P1-06`、`SDD-P2-01`、`SDD-P2-06`。
- 页面根因：应用根节点固定且部分页面缺少自己的 `min-height:0/overflow:auto` 容器；账号页面大量 JSX 类无 CSS；部分设计 token 未定义；登录条件返回位于 Hooks 中间，切换认证状态会触发 React error #300。
- 自动翻译根因：插件和消息开关虽开启，但 Provider 配置未形成统一有效门禁；AI 设置 DB Session 使用错误对象；消息读取 Worker 没有注入运行时设置，导致保存后的密钥/模型不被翻译路径使用。
- 后端修复：统一 `_auto_translate_enabled`；AI settings 返回 `ready/blocked_reason`；插件关闭时手动翻译 API 明确拒绝；Legacy 数字 ID/V2 UUID 缓存键统一；RuntimeAISettingsManager 使用真正 session factory；翻译 Worker 注入同一运行时 Provider。
- 插件真实性优化：无可靠 Worker/Hook 的定时、群发、TTS、媒体、自动标签和跟进插件统一返回 `available=false`；前端禁用开关并显示“执行链未接通”，后端拒绝重新启用。
- 前端修复：App 计算唯一 `autoTranslateState` 并下传；Provider 未配置和翻译失败显示可操作提示；四语言补齐状态文案；修复 Hooks 条件返回顺序。
- 样式修复：统一账号中心/详情/QR 和主页面壳、按钮、状态徽标、卡片、表单及移动断点；补齐设计 token；通讯录和发现页使用独立滚动并预留 TabBar/safe area。
- 工程修复：移除 `web_api` import 时自动 `build_app()` 的数据库副作用，CLI 继续显式创建应用。
- TDD/验证：Python `129 passed`，Web `15 passed`，Bridge `63 passed` + lint，Vite build 通过；唯一警告为 Starlette TestClient 上游弃用提醒。
- 真实运行：AI Provider 加密配置并热生效，老挝语→中文探针成功；FastAPI health 200；本机与公网资源均为 `index-CYJQNXms.js` / `index-CBTrxfav.css`。
- 浏览器验收：生产站点桌面 1440×900、移动 390×844 的聊天/通讯录/发现/我均无横向溢出或 React 控制台错误；通讯录和发现具有可用滚动容器。
- 剩余：消息读取翻译尚未异步化；定时/群发插件仍缺可靠 Worker；Playwright 审计脚本需正式纳入仓库测试。

---

## 2026-07-10：修复 V2 消息刷新/发送、AI 翻译并新增“我→全局 AI”

- 根因 1：`ChatPane` 对 V2 会话直接跳过 `refreshTick`，因此独立库有新消息时当前聊天窗口不刷新。
- 根因 2：V2 会话发送仍误调用 Legacy `/api/reply`，没有锁定当前 V2 `account_id/conversation_id`。
- 根因 3：翻译路由只接受整数 message ID，V2 UUID 消息被 FastAPI 参数校验拒绝；前端又跳过 `Unknown` 语言，自动翻译不会执行。
- 新增 V2 `POST /api/v1/conversations/{conversation_id}/reply`：按会话账号调用 Bridge，真实成功后写入独立消息表并返回 local/platform ID。
- V2 当前聊天在轮询 tick 时重新读取独立会话消息；发送与读取统一使用同一数据面。
- 翻译缓存与 API 支持整数/字符串 message ID；Unknown 外语文本也会进入翻译尝试，失败保持可重试而不是伪装成功。
- “我”页面新增全局 AI 入口，集中配置 Provider、模型、密钥、全局提示词、全局回复风格和自动翻译；保存后热生效。
- 聊天容器补齐最小宽度、独立滚动、安全区与稳定 scrollbar，避免布局挤压和输入区遮挡。
- TDD 新增 V2 账号绑定发送落库测试、UUID 翻译测试；Python `122 passed`、Web `12 passed`、Bridge `63 passed`，Vite build 通过。
- 已部署资源：`index-DZE5MIrh.js` / `index-elpJaKRv.css`；FastAPI health、Bridge live/ready 均为 200。
- 运行边界：当前 V2 业务账号状态为 offline；事件端点对已知账号正常接收，未知/历史 acceptance 账号事件返回业务 `account_not_found`，不能宣称真实在线消息已端到端验收。

---

## 2026-07-10：多平台多账号聚合收件箱、通讯录和微信式布局

- 修正产品模型：聊天 `ALL` 现在聚合 Legacy 和 V2 的全部会话，平台层使用 `ALL/WA/...`，平台下使用 `全部账号/WA1/WA2/WA3` 二级筛选。
- 新增前端 `inboxModel`，为每条会话生成账号隔离的 `conversation_key`；相同 JID 在不同账号不会选中错会话、覆盖未读或 React key 冲突。
- `/api/v1/conversations` 新增平台范围、可用平台和账号元数据；新增 `/api/v1/contacts` 独立联系人接口，按平台/账号隔离。
- 通讯录不再只从当前会话临时展示：支持跨平台、账号标签、账号分组、搜索和进入所属会话。
- 重构聊天列表筛选、账号胶囊、会话账号标识、聊天标题账号上下文、空状态 SVG、通讯录 cell list 与滚动容器，降低后台管理感。
- TDD：新增聚合、筛选、相同 ID 跨账号联系人测试；Python `120 passed`、Web `12 passed`、Bridge `63 passed`，Vite build 通过。
- 真实部署验证：Legacy `3` 条 + V2 `2` 条会话可聚合；V2 联系人 `2` 条；FastAPI health 200。
- 当前网页资源：`index-zmRcX5WP.js` / `index-CpWFmy3-.css`。

---

## 2026-07-10：修复第二账号已登录但页面无数据

- 根因：Bridge V2 的事件已成功写入独立业务数据库，但聊天首页仍固定调用 Legacy `/api/conversations` 和 Hermes `state.db`，账号中心也没有把所选账号接入聊天查询。
- 新增 `/api/v1/conversations` 与会话消息 API，严格按 `account_id` 查询独立数据库，响应携带 `account_id/account_name/conversation_id`。
- 聊天列表新增“全部账号/单账号”选择器，选择持久化到本地；账号变化会清空旧会话选择并重新加载对应账号数据。
- ChatPane 对独立数据库会话改用 conversation UUID 读取消息；Legacy 增量链保留用于迁移期旧会话。
- 回归测试覆盖账号 B 会话可见、账号范围隔离、聚合视图及消息详情；Python 全量 `120 passed`。
- 部署后真实验证：独立库当前 `1` 个在线 V2 账号、`2` 个会话、`8` 条消息；`/api/v1/conversations?account_id=all` 返回两条真实会话。
- 当前网页资源：`index-CRFRy-mv.js` / `index-Dewmrv3Z.css`；FastAPI health 200。
- 注意：当前运行实例实际上只登记了 `1` 个 V2 业务账号；用户所说“第二个账号”是相对 Legacy 旧账号而言，不代表独立 V2 数据库已有两个账号。

---

## 2026-07-10：修复网页发送成功后消息不同步与感叹号残留

- 根因：`/api/reply` 通过 Legacy Bridge `3000` 发送成功后，只返回 WhatsApp message ID，没有把 outbound assistant 消息写回页面读取的 Hermes `state.db`。
- 页面首次显示的是 optimistic bubble；随后刷新从数据库重载时该消息消失，失败请求则保留 `failed` 状态并显示感叹号/重试。
- 新增 `StateDB.append_assistant_message`：底层明确发送成功后才写入 active session，并保存 `platform_message_id`。
- `/api/reply` 返回 `local_message_id`；会话详情/增量 API 暴露 `platform_message_id`，前端按本地 ID 和平台 ID 合并，避免成功气泡消失或重复。
- 回归测试覆盖 `48370592796813@lid` 风格 LID 会话：网页直发成功后刷新仍存在同一条 assistant 消息及 WhatsApp message ID。
- 验证：Python `119 passed`；Bridge `63 passed` + lint；Web `9 passed` + Vite build；本机 FastAPI/Caddy health 200。
- 部署：新增并启用 `whatsapp-chat-system.service`，FastAPI 8792 由 systemd 自动重启；当前构建资源为 `index-CZeVLI8-.js` / `index-CdAyXNbe.css`。
- 公网阻断另行确认：`whatsapp.future1.us` 返回 Cloudflare 525，DNS origin 仍指向旧服务器 `34.84.185.169`，不是本次应用代码或当前源站服务故障。
- 真实线上探针通过 Legacy Bridge 发送并立即验证：获得真实 WhatsApp ID、本地消息 ID `271`，增量 API 可读；随后将探针内容编辑为明确测试提示。
- SDD-P1-10 由 `Blocked` 更新为 `Implemented`；完整断线/乱序/历史同步仍待 Bridge V2 真实账号验收。

---

## 2026-07-10：完成 Bridge V2 Task 5/6 代码链与安全影子验证

- 新增独立 `bridge/` Node/Baileys 6.7.22 服务：账号级 session/socket、QR、状态、发送、typing、stop/logout/delete、generation 与独立重连。
- 新增 FileSpool/EventSink：先落盘再 POST、pending/inflight/dead、崩溃恢复、重试退避、422 dead-letter、账号隔离和持久化 sequence。
- Bridge 重启会自动扫描并 replay spool；账号注册复用同一 sink owner，避免双 owner sequence/claim 竞态。
- 同 event ID 对 canonical envelope 做一致性校验；不一致显式 `event_identity_conflict`，不静默吞事件。
- 新增 `/internal/events/whatsapp`：内部 token、request ID、结构化错误、`(account_id,event_id)` 幂等和 payload hash 冲突。
- `message.upsert` 在同一事务 upsert contact/conversation/message/event；账号状态与消息回执均按 sequence/status 单调更新。
- 新增 `message.sent/delivered/read/failed` 事件；重复 receipt occurrence 使用独立事件身份，避免永久 409 spool。
- QR 定时器和读取触发过期均发送 `account.disconnected`；stop 同步离线事件。
- Bridge 状态和 `account.error` 对外仅返回稳定脱敏消息，不暴露 session 路径、token 或底层异常。
- 新增 Alembic `0003`：sequence、payload_hash、消息时间字段、旧数据 canonical hash 回填和 downgrade 冲突保护。
- 多轮规格/代码质量审查修复：401/440 分类、QR 优先级、请求追踪、生命周期竞态、双 sink owner、spool identity conflict、错误脱敏和 event pipeline/socket 状态分离。
- 验证：Python `118 passed`；Bridge `63 passed`；Bridge lint 通过；audit 0 vulnerabilities；Web `9 passed` + Vite build；Alembic 往返和 `git diff --check` 通过。
- V2 在 `127.0.0.1:3100` 完成无真实账号影子验证：live/ready 200、未认证 401、create/status/stop 200；随后停止并清理临时 token/runtime。
- Legacy `127.0.0.1:3000` 与 FastAPI `8792` 保持运行，未切流、未停止 Hermes gateway。
- 尚未宣称完成：真实 QR 扫码、真实收发/回执、双账号同时在线和 Hermes shutdown。

---

## 2026-07-10：修复 Bridge V2 Task 5 代码质量 Important 项

- 按 `account_id` 串行化 delete 与并发 create/connect，消除请求先成功后被进行中删除移除的生命周期竞态。
- QR 过期后保留稳定 expired 语义：重复 GET 持续 `410 qr_expired`，状态归一为 `offline` 且 `has_qr=false`，直到新 QR 或新 connect。
- Node 配置统一以 `WHATSAPP_BRIDGE_INTERNAL_TOKEN` 为权威；兼容旧 `BRIDGE_INTERNAL_TOKEN`，两者同时存在且不同则启动 fail-closed。
- 设置 `requestTimeout=30s`、`headersTimeout=15s`、`keepAliveTimeout=5s`；readiness 绑定 manager 初始化/关闭状态。
- 新增 `manager.closeAll()` 与 SIGTERM/SIGINT 幂等优雅关闭，先停止 HTTP listener，再关闭全部账号 session。
- 严格 TDD：新增测试后 RED 为 33 tests / 8 failed；GREEN 为 33 passed；lint、audit（0 vulnerabilities）和 `git diff --check` 通过。
- 未实现 Task 6 event spool/webhook，未提交代码。

---

## 2026-07-10：修复 Bridge V2 Task 5 规格审查阻断项

- QR API 对齐 SDD/FastAPI/前端：返回 `status=qr_pending` 与 `qr_data_url`，并确保同一 `connection.update` 同时含 QR/connecting 时保持 `qr_pending`。
- close 立即推进 socket generation，使旧 socket 的迟到 open/close 无法覆盖 offline/logged_out/新连接状态。
- 新增每账号独立自动重连：指数退避、上限与 jitter 均可注入；测试使用 fake scheduler，无真实等待。
- stop/logout/delete 取消待执行重连；401 `loggedOut` 不重连；Baileys 6.7.22 的 440 `connectionReplaced` 进入 offline/reconnect。
- Bridge 所有成功、健康、认证失败、路由错误和异常响应均回显合法入站 `X-Request-ID`，否则生成新 ID。
- 严格 TDD：原 19 passed；新增测试后的 RED 为 26 tests / 9 failed；GREEN 为 26 passed；`npm run lint` 与 `git diff --check` 通过。
- 仅修改 Task 5 Bridge 内核/测试，未开始 Task 6 event spool/webhook。

---

## 2026-07-10：推进 SDD-P0-03 / SDD-P1-01 多账户控制面与账号中心

- 明确当前仍未彻底脱离 Hermes：Legacy 消息读取/启动 profile 与现有 Bridge 生命周期仍待迁移。
- 新增账号级 repository/service 和 `/api/v1/accounts` CRUD、connect、qr、logout API；响应不暴露 session path/ref。
- 新增独立 Bridge HTTP Client 契约、loopback 限制、超时和结构化错误。
- Bridge token 未配置时 fail-closed；不再使用固定开发 token。
- Bridge 注册失败补偿删除数据库账号，停用先停止 Bridge 后提交业务状态。
- 新增 Alembic `0002`，补齐 AI runtime timeout/retry 字段；真实完成 upgrade→downgrade→upgrade 往返。
- 前端新增微信式 WhatsApp 账号中心：列表、状态、详情、主账号、启停、登出、高危删除、QR 页面。
- 账号状态只信服务端；新账号默认自动回复关闭；Bridge 未配置时明确失败，不展示假二维码。
- 移除用户可见 Settings 中的 Hermes profile/path/CLI 账号入口。
- 四语言新增账号中心文案；修复统一错误 envelope 解析和写操作成功后刷新失败误报。
- 双阶段审查发现并修复孤儿账号、停用顺序、弱默认 token、旧 Hermes UI、错误解析等阻断问题。
- 验证：Python `106 passed`；Node `9 passed`；Vite build 通过；Alembic 往返通过；线上 health/新 JS 200；未认证账号 API 401。
- 尚未完成：Node/Baileys Bridge V2、内部状态事件、真实扫码/收发、多账号隔离和最终 Hermes shutdown。

---

## 2026-07-10：完成 SDD-P0-01 独立 Settings 与问鼎 AI Provider

- 新增独立 `AISettings`，只从 `WENDING_AI_*` 环境变量读取 AI 配置；默认 URL、模型、超时、重试分别为 `https://wendingai.future1.us/v1`、`gpt-5.3-codex-spark`、90、2。
- `AppConfig` 保留 Legacy 路径和业务配置兼容，但 AI 设置不再从 Hermes `config.yaml` 读取。
- 新增 `WendingAIProvider`，统一调用 `/chat/completions`，映射 401/429/5xx/timeout 结构化错误，仅 429/5xx/timeout 有限重试。
- 新增 `AIService`，实现联系人 override > 账号 AI Profile > 全局默认的模型解析和来源标记。
- Rewriter 的智能改写、手动翻译、自动翻译移除散落的 `requests.post()`，统一经过 AIService/Provider。
- 新增 mock HTTP server、错误重试、密钥脱敏、模型优先级、调用审计、结构化失败和 Rewriter 接线测试。
- 设置接口新增 effective model/source 和安全的 `/api/v1/ai/settings`；翻译失败不会把原文伪装成翻译结果。
- Provider 默认每次调用使用独立 Session；环境值会做 strip、范围限制和 Base URL 脱敏规范化。
- 验证：全量 `72 passed, 1 warning`；前端 `npm run build` 通过；ChatSync `4 passed`；`py_compile`、`git diff --check` 通过。
- 未写入真实 API key，未修改或重启生产服务；状态为 `Implemented`，待部署和真实凭据安全探测后进入 `Verified`。

---

## 2026-07-10：建立强制 SDD 文档体系

- 新建 `docs/sdd/` 权威规格目录：总纲、产品需求、系统架构、数据模型、API/事件、优化待办、开发流程、迁移上线。
- 将全部待优化项按 P0/P1/P2 收入 `docs/sdd/05-optimization-backlog.md`，补齐状态、需求关联和验收标准。
- 将独立运行、问鼎 AI 默认配置、多 WhatsApp 账号、Outbox、Worker、插件接线、前端 UX、安全和可观测性统一规格化。
- `AGENTS.md` 与 `CLAUDE.md` 写入强制 SDD 流程：先规格和需求 ID，再计划/TDD/双阶段审查/门禁/部署验证。
- `TODO_AGENT.md` 降级为当前执行视图；旧 `docs/SDD.md` 标为 Deprecated；`docs/ARCHITECTURE.md` 改为新规格入口和 Legacy 基线摘要。
- 后续只有达到 `Verified` 的 SDD 需求才能标记完成。
- 本次只修改文档和开发治理规则，不改生产业务代码；当前 8792 Uvicorn 启动通知属于现有 Legacy 服务状态。

---

## 2026-07-10：独立运行 + 问鼎 AI + 多 WhatsApp 账号方案

- 完成现有运行链审计：确认 AI 配置、消息数据库、CLI fallback、Bridge 生命周期和账号 UI 均依赖 Hermes profile/gateway。
- 确认当前 Bridge 为单进程单全局 socket、单 session 目录、内存 `messageQueue`，不能直接满足可靠多账号。
- 确认问鼎 AI OpenAI-compatible 入口可达：`GET /v1/models` 未认证返回 401，说明域名与认证网关正常；聊天接口应使用 `POST /v1/chat/completions`。
- 定稿目标架构：FastAPI 控制面 + 独立多账号 Baileys Bridge + 独立业务数据库 + Worker + React 管理台。
- 默认 AI：`https://wendingai.future1.us/v1` / `gpt-5.3-codex-spark`；模型优先级为联系人 > 账号 > 全局。
- 设计 `account_id` 全链路隔离、webhook 幂等事件、Outbox 发送、定时/群发 Worker、旧 Hermes 只读 importer 和分阶段切换方案。
- 新增详细实施文档：`docs/plans/2026-07-10-standalone-wendingai-multi-account.md`。
- 本次仅完成审计和方案，不修改生产运行代码、不停止 Hermes gateway。

---

## 2026-07-10：TabBar 图标渲染 + 模型默认值透出 + 插件真正生效

### TabBar 图标

- 根因：`.wx-tab-btn > span[aria-hidden] svg` 在 styles.css 中无尺寸规则，导致 SVG 渲染为 0 宽
- 修复：补 22×22 尺寸 + currentColor 描边 + active 态品牌色

### 模型选择

- 根因：`config.yaml` 的 `model.default` 透出但前端用硬编码 `gpt-5.3-codex-spark` 当占位，看不到真实默认模型
- 修复：`/api/settings` 现返回 `model.default` 与 `model.base_url`，前端把 `settings.model.default` 注入联系人默认、设置页占位文本和"我"页
- 联系人 AI 模型输入留空时，明确提示"留空则继承 `<model.default>`"

### 插件真正生效

- 根因：插件 flag 写入 web_settings 后没有任何后端代码读它
- 修复：
  - `_auto_translate_enabled` 同时读 `plugins.auto_translate` 和 `message_ops.auto_translate`
  - `/api/reply` 检查 `quick_reply` 插件，关闭时 `preview_only` 请求返回 `success: false, plugin: 'quick_reply'`
  - `/api/settings` 现返回完整 `plugins` 状态字典
  - 插件目录新增 `hooks` 与 `status_when_on`，前端 DiscoverPage 与 ToolsPanel 显示当前开关对应的后端接口
  - 前端 `autoTranslate` 同步考虑 `plugins.auto_translate` flag

### 验证

- `npm run build`：通过
- `pytest -q`：50 passed（含 2 个新测试覆盖 `/api/settings` 元数据 + 插件 gate）
- `node --test tests/chatSync.test.js`：4 passed
- live `/api/health`：200
- live `/api/settings` 返回 `model.default` 与 `plugins` 字典
- live CSS 命中 `.wx-tab-btn > span[aria-hidden] svg{width:22px;height:22px;stroke:currentColor;...}`

---



### 会话列表与图标

- 左滑操作层改为默认完全隐藏，仅滑动后显示置顶/删除
- 加入 X/Y 方向锁、`touch-action: pan-y`、单行展开和滑动防误触
- 搜索、设置、置顶、删除 SVG 显式使用 `currentColor`
- 删除会话增加确认、失败提示和置顶状态恢复

### 消息发送与 API

- 前端补齐 `api.delete`
- OPTIONS 预检绕过 auth middleware，普通 API 认证保持不变
- 普通发送严格检查真实 `success === true`，后端失败返回 502 和 `retryable`
- 失败消息保留目标、原文和模式；可重试错误支持原地重试
- 群发按逐项真实结果返回成功、部分成功、失败统计
- Hermes JSON 发送输出缺失 `success: true` 时不再默认成功
- 删除不存在的定时任务返回 404

### 消息同步

- SQLite 增量查询改为严格按消息 ID 排序，与 `id > cursor` 一致
- 增量 API 返回 `next_after_id` 和 `has_more`
- 前端连续排空最多 10 批增量消息，避免一次超过 100 条时漏消息
- 请求追踪器阻止旧会话响应覆盖当前会话
- 修复发送后延迟刷新可能使新会话加载失效的竞态

### 移动端聊天

- 进入具体聊天后隐藏根 TabBar，输入区独占底部安全区
- textarea 按真实 `scrollHeight` 自动增高，移动端字号 16px
- 中文输入法组合阶段 Enter 不触发发送
- 用户查看历史时不强制滚底，显示新消息计数按钮
- 联系人抽屉 AI 风格入口改为抽屉内切换 Tab

### 工程质量

- 四语言 i18n keys 全量对齐
- StaticFiles 在最小测试夹具缺少 assets 目录时仍能启动 SPA
- 新增 ID 游标乱序时间戳与 API 分页测试

### 验证与部署

- `npm run build`：通过
- `pytest -q`：48 passed
- `node --test tests/chatSync.test.js`：4 passed
- `git diff --check`：通过
- 线上 `/api/health`：200
- 线上 JS：`index-X_NsIE3q.js`，200，248740 bytes
- 线上 CSS：`index-BWXtslEL.css`，200，43681 bytes
- CORS OPTIONS：200；未认证普通 API：401

---

## 2026-07-10：第一步——消息实时刷新与防串线

### 修复

- 初次会话加载成功后正确标记当前会话，恢复 `refreshTick` 增量拉取
- 新增会话请求追踪器；切换联系人或卸载时使旧请求失效
- 历史分页、发送后刷新均显式绑定目标联系人，避免依赖变化中的闭包

### 新增测试

- `web/tests/chatSync.test.js`：4 个请求生命周期回归测试全部通过

### 验证

- `node --test tests/chatSync.test.js`：4/4 通过
- `npm run build`：通过
- 新资源：`index-BTN4u_Pt.js`
- 线上 `/assets/index-BTN4u_Pt.js`：200，235898 bytes
- `/api/health`：200
- Python 全测仍为历史状态：41 passed / 3 failed（i18n 与 StaticFiles 测试夹具）

---

## 2026-07-10：前后端微信体验与可靠性审计

### 审计范围

- 前端：App、会话列表、聊天页、通讯录、发现、我、设置、工具、CSS、i18n
- 后端：消息分页/增量、发送、认证、CORS、翻译、群发、定时任务、插件、持久化

### 真实验证

- `npm run build`：通过
- `pytest -q`：41 passed / 3 failed
- `/api/health`：200
- 跨域 OPTIONS 预检：401，被 auth middleware 拦截

### 主要结论

- 当前聊天增量刷新失效，快速切换会话存在消息串线风险
- 发送失败可能误报成功；增量游标可能造成消息永久遗漏
- `api.delete` 缺失；定时发送尚无执行 worker
- 移动端聊天层级、左滑手势、输入区与四 Tab 信息架构仍需重构
- 会话计算、翻译、SQLite 索引与运行态配置持久化需要性能和可靠性治理

### 文档更新

- `docs/TODO_AGENT.md`：新增 P0/P1/P2 可执行优化清单
- `docs/PROJECT_MEMORY.md`：更新当前关键风险和验证结果

---

## 2026-07-09 14:42 UTC

### 修复：StaticFiles `/assets` 404 bug（部署失败根因）

**问题**：前端 JS/CSS 文件构建成功，但浏览器访问返回 404。
**根因**：Starlette StaticFiles mount path strip 机制，`/assets/index.js` 查找 `dist/index.js` 而非 `dist/assets/index.js`。
**修复**：修改 `web_api.py`，mount 时 `directory=frontend_dist / 'assets'`。

**文件**：
- `src/whatsapp_chat_system/web_api.py`（修改 mount directory）

**验证**：
```
curl /assets/index-DtN9hy5s.js → 200 OK (235KB) ✅
curl /assets/index-CJfNWq4L.css → 200 OK (42KB) ✅
curl / → 200 text/html ✅
```

---

### 体验优化：前端 UX 增强

**骨架屏**：ChatPane 加载时显示 8 条左右交替骨架气泡（带 shimmer 动画），替代纯文字 Loading。
**输入区**：发送按钮加 spinner + brand-green 背景 + 灰色 disabled 态；Mode pill 加 AI 徽章。
**TabBar**：统一 CSS 类 `.wx-tab-bar` / `.wx-tab-btn`；active 态 scale 即时反馈。
**页面切换动画**：`.wx-page` 上滑渐入（200ms）；`.wx-chat-layout` 右滑进入（180ms）。
**Toast**：底部弹出 + 磨砂玻璃背景 + scale 组合动画。
**空状态**：聊表为空时插图 emoji + 标题 + 描述文字二级结构。

**文件**：
- `web/src/components/ChatPane.jsx`
- `web/src/components/ChatList.jsx`
- `web/src/components/TabBar.jsx`
- `web/src/styles.css`
- `web/src/i18n.js`（新增 `noConversationsHint` 四语 key）

**部署资源**：`index-DtN9hy5s.js` / `index-CJfNWq4L.css`

---

## 2026-07-09 13:XX UTC

### Bug 修复：前端滚动/置顶/样式 P0 级问题

| Bug | 修复 | 文件 |
|-----|------|------|
| mobile ChatPane 高度坍塌（grid 100% 失效） | `.wx-shell {height:100dvh}` + `.wx-chat {min-height:0}` | styles.css |
| pinned 置顶逻辑完全失效（对象数组 vs string[]） | 直接用 `conversations[i].pinned` 布尔字段 | App.jsx, ChatList.jsx |
| ChatList 设置按钮是 "+" 图标（应为 gear） | 换成 gear SVG | ChatList.jsx |
| Chat header 循环切换按钮（WeChat 无此功能） | 移除 | ChatPane.jsx |
| 新消息不自动滚底（useLayoutEffect 依赖 length） | 改依赖 `messages[messages.length-1]?.message_id` | ChatPane.jsx |
| `refreshTick` useEffect 依赖 messages 引发死循环 | 移除 messages 依赖 | ChatPane.jsx |
| `wx-text-muted-dark` CSS 变量不存在 | 删除无效覆盖行 | styles.css |
| SettingsPanel 保存/关闭按钮无样式 | 加 `wx-primary-btn` / `wx-icon-btn` class | SettingsPanel.jsx |
| ContactsPage 无搜索 | 加搜索框（name/ID 过滤） | ContactsPage.jsx |
| platform-* 类名全部无 CSS | 补全 9 个 platform-* 类 | styles.css |

---

## 2026-07-09 部署信息

- **当前线上 JS**：`index-DtN9hy5s.js`（235KB）
- **当前线上 CSS**：`index-CJfNWq4L.css`（42KB）
- **后端日志**：`/tmp/whatsapp-live.log`
- **后端测试**：`43 passed, 1 failed`（早期遗留 i18n key 缺失）
