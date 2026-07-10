# CHANGELOG_AGENT.md — Agent 变更记录

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
