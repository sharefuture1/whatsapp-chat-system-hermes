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
  - [x] 独立库会话 API 按 `account_id` 查询；前端支持“全部账号/单账号”筛选和独立消息详情
  - [x] 当前真实扫码账号的 2 个会话、8 条消息已在页面 API 可见
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

- `npm run build`：✅ 通过
- `pytest -q`：✅ 120 passed
- `node --test web/tests/*.test.js`：✅ 9 passed
- `cd bridge && npm test`：✅ 63 passed
- Bridge lint：✅ 通过
- Bridge production audit：✅ 0 vulnerabilities
- Alembic upgrade → downgrade → upgrade：✅ 通过
- `/api/health`：✅ 200
- Legacy 网页直发同步探针：✅ 真实 WhatsApp ID + local ID + 增量 API 可读
- V2 `3100` 影子 live/ready：✅ 200；未认证 API：401；create/status/stop：200
- 线上资源：`index-CRFRy-mv.js` / `index-Dewmrv3Z.css`，本机 FastAPI 资源 200
- V2 独立会话 API：✅ 当前 1 个在线业务账号、2 个会话、8 条消息可读；账号筛选已部署
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
