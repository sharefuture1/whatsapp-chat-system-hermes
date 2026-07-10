# TODO_AGENT.md — 待办任务

## 当前优先级排序

> 权威优化规格：`docs/sdd/05-optimization-backlog.md`。本文件只显示当前执行状态；新增、删除或改变需求必须先修改 SDD。

### P0 — 独立化与多账号主线

- [ ] **Phase 1：独立配置与问鼎 AI Provider（代码已实现，待生产验收）**
  - AI 配置已独立从 `WENDING_AI_*` 环境变量加载，不要求 Hermes `config.yaml`
  - 默认 `https://wendingai.future1.us/v1` + `gpt-5.3-codex-spark`
  - Provider 已统一超时、有限重试、结构化错误；AIService 已实现联系人 > 账号 > 全局模型优先级
- [ ] **Phase 2：建立带 `account_id` 的业务数据库**
  - accounts / contacts / conversations / messages / AI profiles / outbox
  - `(account_id, remote_jid)` 隔离，同账号 WhatsApp message ID 幂等
- [>] **Phase 3：抽出独立 Bridge V2，先跑通单账号**
  - [x] 账号控制面 API、Bridge Client 契约、fail-closed 安全配置
  - [x] Task 5 Node/Baileys 基础：账号 session/socket、QR/状态、stop/logout/delete、自动重连、请求 ID、生命周期竞态防护、统一 token 与优雅关闭
  - [x] Task 6 内部事件接收与持久化 spool：幂等/hash、sequence、事务落库、回执、重启 replay、dead-letter
  - [ ] 使用真实测试账号验收扫码、session 恢复、入站、出站 message ID 和回执
- [>] **Phase 4：Bridge V2 多账号隔离**
  - [x] 迁移期统一收件箱：ALL 聚合 Legacy + V2；平台 `ALL/WA`，账号 `WA1/WA2/...`
  - [x] 会话使用账号隔离 `conversation_key`，避免相同 JID 跨账号冲突
  - [x] 独立联系人 API 与多平台/多账号通讯录筛选、分组和搜索
  - [x] 当前真实数据验证：Legacy 3 条会话 + V2 2 条会话、2 个联系人
  - [ ] 再创建并扫码第二个 V2 业务账号，验证两个账号同时在线
  - [ ] 验证 A 断线、登出、发送不影响 B；相同 JID 数据和 socket 严格隔离
- [ ] **Phase 5：Outbox、定时与群发 Worker**
  - 定时任务真实执行，群发支持进度/取消/幂等/逐项结果
- [>] **Phase 6：前端 WhatsApp 账号中心**
  - [x] 真实账号 API 驱动的列表、详情、状态、高危删除 UI
  - [x] 用户可见设置移除 Hermes profile/path/CLI 入口
  - [ ] Bridge V2 接通后完成真实 QR、实时状态和账号切换验收
- [ ] **Phase 7：只读迁移旧 Hermes 数据并切换**
  - 导入报告、双写观察、可回滚；切换后停止 Hermes gateway

详细计划：`docs/plans/2026-07-10-standalone-wendingai-multi-account.md`。

### P0 — 阻断核心聊天体验

- [x] **完成移动会话两级导航和发送/翻译可靠性修复**
  - 390px 初始全屏会话列表；进入聊天隐藏 TabBar，返回键清空 `selectedId`
  - 桌面维持双栏，刷新时不再自动选择首会话
  - `tmp-*`、pending、failed 消息禁止进入翻译请求，真实 ID 替换乐观 ID
  - 服务端刷新保留最后一条自己消息的 `sent` 状态
  - 置顶去重、未读纯红点、HH:MM 和 5 分钟时间合并完成
  - textarea 根据 `scrollHeight` 增长到 140px；模式改为三选一
  - Web 35、Python 129、Bridge 63 通过，移动/桌面真实 Chromium 验收通过

- [x] **修复消息页周期性闪烁并收敛为微信聊天布局**
  - 账号轮询在无变化时保留 React 数组引用，Workspace callback 不再随每轮账号刷新重建
  - ChatPane 初始加载仅依赖稳定会话 identity，不再因完整 `uiSettings` 对象变化清空消息
  - 自动翻译按 message ID 去重 in-flight 请求
  - 顶部仅保留返回、联系人、状态和“…”；双方方形头像与左右气泡镜像；译文内嵌原气泡
  - 输入区改为微信式表情/输入/加号，AI/直发/翻译与快捷表情收纳进折叠工具面板
  - Playwright 15 秒连续采样中，首次加载后 80 条消息、容器高度与滚动位置保持稳定；390×844 无横向溢出

- [x] **修复全站页面滚动、响应式与账号页面样式**
  - 聊天、通讯录、发现、我、账号中心/详情/QR 使用独立滚动页面壳
  - 桌面 1440×900、移动 390×844 无横向溢出；生产浏览器控制台无 React 错误
  - 修复 Hooks 条件返回导致的生产 React error #300

- [x] **修复自动翻译插件开启但不调用 AI**
  - 插件、消息开关、Provider 配置统一为一个有效门禁
  - 运行时加密设置热生效，翻译 Worker 使用同一 Provider
  - Legacy 数字 ID/V2 UUID 均支持；失败显示配置或 Provider 错误
  - 真实老挝语→中文 AI 探针通过

- [ ] **自动翻译异步化**
  - 当前读取消息仍可能同步等待模型；迁移为任务队列、缓存回填、失败重试和实时更新

- [x] **修复会话列表左滑与 SVG 图标**
  - 操作层默认完全隐藏，仅左滑后显示
  - X/Y 方向锁、`touch-action: pan-y`、单行展开、滑动后防误触
  - 置顶/删除/设置/搜索 SVG 显式使用 `currentColor`

- [x] **修复发送结果误报成功**
  - 普通发送严格检查后端 `success === true`
  - 失败消息保留原始目标/文本/模式并支持原地重试
  - 群发按真实逐项结果汇总成功、部分成功和失败

- [x] **修复增量游标可能永久漏消息**
  - 增量查询统一按消息 ID 排序
  - API 返回 `next_after_id` 与 `has_more`，前端连续排空积压批次

- [x] **修复网页直发成功后刷新丢消息/感叹号残留**
  - Bridge 明确成功后将 outbound assistant 消息与 WhatsApp ID 写回 `state.db`
  - `/api/reply` 返回 local/platform 双 ID，前端稳定去重合并
  - 真实线上探针验证发送、本地落库和增量 API 同步

- [x] **移动端进入聊天后隐藏根 TabBar**
  - 聊天输入区独占底部安全区

- [x] **修复会话左滑与纵向滚动冲突**
  - 已加入方向锁、单行展开与删除确认

- [x] **补齐 `api.delete`**
  - 定时任务/插件删除请求可正常发出

- [ ] **定时发送入口下线或实现真实 worker**
  - 当前只保存任务，不会在指定时间执行

- [x] **修复 V2 当前聊天不刷新与发送走错数据面**
  - V2 会话随轮询重新加载独立消息 API
  - V2 回复按当前 conversation/account 调用 Bridge，成功后写独立消息库
- [x] **修复 V2 UUID 消息 AI 翻译失败**
  - 翻译 API 与缓存接受整数/字符串 message ID
  - Unknown 外语文本不再被前端直接跳过
- [x] **全局 AI 设置移入“我”页**
  - Provider、模型、密钥、全局提示词、回复风格、自动翻译集中配置并热生效
- [ ] **重新上线真实 V2 账号并做消息/翻译端到端验收**
  - 当前登记业务账号为 offline；需扫码/连接后验证真实入站、V2 出站 ID、刷新和 AI 翻译

### P1 — 微信核心体验与可靠性

- [x] 中文输入法组合阶段 Enter 不得误发送
- [x] 输入框根据 `scrollHeight` 自动增高，移动端字号至少 16px
- [x] 新消息到达且用户在看历史时显示“新消息”按钮，不强制滚底
- [x] 联系人抽屉“AI 风格”按钮保持抽屉打开并切换 Tab
- [ ] 会话未读改为后端真实计数；暂时无法统计时只显示红点
- [ ] 通讯录改为独立联系人数据源、备注名、分组和索引
- [ ] “发现”改为“工作台”，插件/群发/定时进入二级页
- [ ] “我”页面移除当前联系人信息，只保留操作员和应用设置
- [ ] 聊天头部收敛为返回、名称、状态和单一“…”入口
- [ ] Emoji 快捷项和 AI 模式移入表情/更多面板
- [ ] 设置移动端改为全屏分级页面
- [ ] 翻译从消息读取请求中异步化
- [ ] 会话列表改 SQL 分页并增加必要 SQLite 索引
- [ ] 群发改后台任务、限速、进度、取消和幂等
- [ ] JSON 运行态配置迁移 SQLite 或增加文件锁和原子写入
- [ ] 鉴权改 HttpOnly Cookie、服务端 token 哈希，移除默认弱密码
- [ ] 插件开关必须真正控制对应 API 与 worker
- [x] CORS 预检 OPTIONS 绕过 auth middleware

### P2 — 工程与视觉精修

- [ ] 清理 `styles.css` 重复规则和旧 `.wx-tabbar*` 类
- [ ] 补齐 JSX 使用但未定义的 CSS 类
- [ ] 功能性 emoji/字符图标全部换统一 SVG Icon
- [ ] 统一 Avatar，支持真实头像与失败回退
- [ ] 补齐顶部/底部 safe area、focus-visible、dialog focus trap、aria-live
- [ ] 暗色默认跟随系统，并支持 `prefers-reduced-motion`
- [x] 补齐四语言 i18n keys
- [x] 修复 StaticFiles 测试夹具兼容性
- [ ] 增加移动端 Playwright 主链路回归测试

### 当前验证结果（2026-07-10）

- `npm run build`：✅ 通过，资源 `index-DRPbZjTf.js` / `index-n1Ei7oEG.css`
- `pytest -q`：✅ 129 passed
- `node --test web/tests/*.test.js`：✅ 35 passed
- `cd bridge && npm test`：✅ 63 passed
- Bridge lint：✅ 通过
- Bridge production audit：✅ 0 vulnerabilities
- Alembic upgrade → downgrade → upgrade：✅ 通过
- `/api/health`：✅ 200
- 真实 AI 翻译探针：✅ 老挝语→中文，运行时 Provider 生效
- 生产页面审计：✅ 桌面/移动四主页面无横向溢出、无 React 控制台错误，通讯录/发现滚动容器可用
- 本机与公网静态资源哈希：✅ 一致
- Legacy 网页直发同步探针：✅ 真实 WhatsApp ID + local ID + 增量 API 可读
- V2 `3100` 影子 live/ready：✅ 200；未认证 API：401；create/status/stop：200
- 统一收件箱：✅ Legacy 3 条 + V2 2 条会话聚合；平台/账号二级筛选已部署
- 多账号通讯录：✅ V2 2 个联系人可读并与 Legacy 联系人聚合展示
- 第二个 V2 业务账号同时在线：⏳ 尚未创建/登记，需继续扫码验收

### P2 — 工程与视觉精修

- [ ] 左滑置顶/删除的移动端 touch 体验优化
- [ ] 深色模式完善（目前仅基础 token）
- [ ] 多语言切换实时生效（目前需刷新）
- [ ] 插件系统 UI（ToolsPanel）完成度验证

---

## 已完成 ✅

- [x] StaticFiles `/assets` 404 根因定位 + 修复
- [x] mobile ChatPane 高度坍塌
- [x] pinned 置顶逻辑
- [x] 骨架屏 + 页面切换动画
- [x] 前端 UX 优化（compose bar / tab bar / 空状态）
- [x] CLAUDE.md / AGENTS.md 建立
- [x] 文档体系完善（PROJECT_MEMORY / DECISIONS / CHANGELOG / TODO）
