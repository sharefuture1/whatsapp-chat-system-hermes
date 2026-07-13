# 2026-07-13 — 发现页/设置页微信化、定时与群发降级

## 目标

1. **发现页微信化**：取消“总览网格 + 插件目录 + AI 人设”三大块塞同一页；只保留运营概览卡片与受控 AI 人设（受控目录、安全边界、不可用插件不再混入此处）。
2. **设置页微信化**：六个 Tab 收敛为“AI 与回复 / 全局 AI / 界面 / 账号中心 / 插件中心 / 安全”六项；移动端使用单行横滑导航与底部固定操作栏；桌面侧栏保留。
3. **定时与群发降级**：在 Worker 真实接通前，从发现页和设置 Tab 中移除“定时发送”和“群发”两块表单；API 仍保留，但写入端返回 503/501 让 UI 不能再提交。
4. **保留功能契约**：受控 AI 人设、插件目录、自动翻译、全局 AI 设置、账号中心仍可访问并运行。

## 改动

### SDD / 文档

- `docs/sdd/01-product-requirements.md`：新增 `UX-013`，明确发现页/设置页结构、定时/群发前置条件。
- `docs/CHANGELOG_AGENT.md`：记录本轮“发现与设置微信化、定时与群发降级”。
- `docs/PROJECT_MEMORY.md`：更新受控 AI 人设与插件中心位置。
- `docs/TODO_AGENT.md`：勾选已闭环项，新增 SDD-P0-06/07 实现条件。

### 后端（最小）

- `src/whatsapp_chat_system/web_api.py`：
  - `POST /api/schedule` / `POST /api/broadcast`：在 Worker 未启用时直接 `503 not_implemented`（错误码 `scheduler_not_connected` / `broadcast_not_connected`），不再写入本地 JSON。
  - `GET /api/schedule` / `GET /api/broadcast`：保留但返回空 `items`，便于前端不在旧 localStorage 残留上 500。
  - 插件目录中 `schedule` / `broadcast` 的 `available` 仍为 `false`，并补充 `unavailable_reason`。

### 前端

- `web/src/components/DiscoverPage.jsx`：移除插件目录区块（保留在 Me → 插件中心），保持受控 AI 人设与运营概览。
- `web/src/components/SettingsPanel.jsx`：
  - 移除 `tools` Tab 整体（不再出现定时/群发表单）；
  - Tab 文案沿用 i18n key，不出现硬编码中文/英文混排；
  - 保存按钮分组在 footer，主题切换与语言切换保留。
- `web/src/components/MePage.jsx`：新增“插件中心”入口，删除冗余“设置”/“账号与连接”双重入口，结构更接近微信“我”。
- `web/src/components/ToolsPanel.jsx`：删除（不再使用）。

### 测试

- 后端新增：`tests/test_web_api.py` 中 `test_schedule_returns_503_when_no_worker`、`test_broadcast_returns_503_when_no_worker`。
- 前端新增：
  - `web/tests/discoverPageWechat.test.js`：断言发现页不再含插件目录区块、只保留受控 AI 人设与概览。
  - `web/tests/settingsWechat.test.js`：断言设置不含定时/群发 Tab，且移动端 nav 使用横向滚动布局。
  - `web/tests/pluginCenterEntry.test.js`：断言 Me 页包含“插件中心”入口。
  - 现有 `mobileWechatUx.test.js` 增补滚动规则。

### 风险与回滚

- 已部署的定时/群发历史 JSON 不会破坏，只是不会再被显示或写入。
- 若用户已通过旧 UI 看到定时/群发，刷新后即从界面消失；他们提交的旧请求会得到 `503`，不会消耗 Worker 配额。
- 回滚：仅需恢复 `DiscoverPage.jsx` / `SettingsPanel.jsx` 的旧版本与 `POST /api/schedule` / `/api/broadcast` 旧实现。
