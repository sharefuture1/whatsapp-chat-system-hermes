# TODO_AGENT.md — 待办任务

## 当前优先级排序

### P2 — 需要做但不紧急

- [ ] **验证 ContactsPage 搜索功能**
  - 搜索框已加，需要在浏览器验证过滤逻辑是否正确
  - 文件：`web/src/components/ContactsPage.jsx`

- [ ] **Settings platforms tab CSS 完善**
  - `.platform-toolbar` / `.platform-card` / `.platform-group` 已加基础样式
  - 但 platforms 列表渲染逻辑和保存逻辑需人工测试验证
  - 文件：`web/src/components/SettingsPanel.jsx`

- [ ] **消息同步 gap 调查**
  - 部分聊天记录未同步（原因不明）
  - 需在真实 WhatsApp 对话中观察 message fetch 行为

- [ ] **i18n 缺失 keys 补全**
  - `test_all_t_keys_exist_in_dict` 失败，60+ key 缺失
  - 不影响功能但影响测试通过率

### P3 — 未来优化

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
