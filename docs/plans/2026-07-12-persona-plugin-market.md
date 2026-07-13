# 会话级 AI 人设插件 Implementation Plan

> **For Hermes:** 使用 `subagent-driven-development` 按任务逐项实现并执行双阶段审查。

**Goal:** 在发现页提供可见、可启用的人设库；操作员能为当前聊天选择人设，AI 智能回复真实注入该人设，并可随时切回默认风格。

**Architecture:** 首版使用受控内置人设目录，而非运行第三方代码或展示 GitHub 来源。人设以稳定 `id`、名称、场景、简述、prompt 约束组成；全局插件开关和联系人级 `persona_id` 都存入现有受控设置。Legacy 回复链路从联系人 override 解析人设并将服务端 prompt 注入统一 Rewriter；未选择或插件关闭时必须完全回退原有默认回复。

**Tech Stack:** FastAPI/Pydantic、现有 JSON 设置持久化、React 18/Vite、pytest、Node 静态契约测试。

---

### Task 1: 固化可扩展人设目录与安全解析 [FR-PLG-007, FR-AI-012]

**Files:**
- Create: `src/whatsapp_chat_system/personas.py`
- Create: `tests/test_personas.py`

**Acceptance:**
- 目录包含 `tong-jincheng`、`professional-service`、`mature-uncle` 三种人设和 `default` 回退。
- 外部未知 id、插件关闭、联系人未选人设均不可进入模型 prompt。
- 人设仅提供受控文本约束，不执行脚本、不读取文件、不访问网络。

**TDD:**
1. 先写目录/解析失败测试并运行 `pytest tests/test_personas.py -q`，确认因模块缺失失败。
2. 最小实现受控 catalog、`list_personas()`、`resolve_persona()`。
3. 运行同一测试确认通过。

### Task 2: 让后端目录和智能回复真实接线 [FR-PLG-007, FR-AI-012, API-PLG-007]

**Files:**
- Modify: `src/whatsapp_chat_system/web_api.py`
- Modify: `src/whatsapp_chat_system/router.py`
- Modify: `src/whatsapp_chat_system/rewriter.py`
- Modify: `tests/test_web_api.py`

**Acceptance:**
- `GET /api/personas` 返回安全的展示字段与当前插件可用状态。
- `POST /api/personas/{persona_id}/assign` 为指定联系人保存或清除人设，未知 id 返回 404；插件关闭返回 409。
- 回复预览响应包含实际 `persona` 元数据；智能回复的 system prompt 包含受控人设约束，直发/翻译不改变。

**TDD:**
1. 添加 API 与 prompt 注入的失败测试，运行 focused pytest 验证 RED。
2. 实现最小 API/override 解析/prompt 注入。
3. 重新运行 focused pytest 与全量 pytest。

### Task 3: 发现页与聊天页展示可操作人设 [UX-007, UX-005]

**Files:**
- Modify: `web/src/components/DiscoverPage.jsx`
- Modify: `web/src/components/ChatPane.jsx`
- Modify: `web/src/styles.css`
- Modify: `web/src/i18n.js`
- Modify/Create: `web/tests/personaUi.test.js`

**Acceptance:**
- 发现页出现“AI 人设”区域，展示三种人设卡片和启用状态，不展示 GitHub 来源。
- 当前聊天的“…”菜单能打开人设选择；选择立即保存，显示当前人设标签；默认项可清除。
- 全部用户可见文本进入 en/zh/th/lo；不会增加全局设置到聊天页。

**TDD:**
1. 添加源码契约测试并先执行 `node --test tests/personaUi.test.js` 验证 RED。
2. 最小实现 UI、样式和 i18n。
3. 运行契约测试及 `npm run build`。

### Task 4: 审查、部署与真实验证 [QA-001]

**Acceptance:**
- 规格符合性审查与代码质量审查均 APPROVED。
- `pytest -q`、`node --test tests/*.test.js`、`npm run build`、`git diff --check` 通过。
- 部署到 8792 后验证 health、静态资源、`/api/personas` 鉴权接口和浏览器人设选择→AI 预览链路。
- 状态只能标记 Implemented，除非真实 AI Provider + WhatsApp 发送完整验收通过。
