# CHANGELOG_AGENT.md — Agent 变更记录

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
