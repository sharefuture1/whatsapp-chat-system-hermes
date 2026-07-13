# SDD-P0-08 受控 AI 人设 — 实施计划

## 目标

让用户可以在发现页选择/启停受控 AI 人设，在聊天页为当前联系人切换人设，AI 回复真实携带人设 prompt；UI 不显示任何外部源/仓库信息。

## 范围

- `FR-PLG-007` 受控内置人设
- `FR-PLG-008` 会话级人设
- `FR-AI-012` 智能回复 persona_id 透传
- `SDD-P0-08`

## Files

Create:
- `src/whatsapp_chat_system/api/v1/personas.py` — V1 personas router
- `tests/test_personas_api.py` — 9 RED cases
- `web/tests/personaPlugins.test.js` — 4 RED cases
- `docs/plans/2026-07-12-persona-plugins.md` — 本计划

Modify:
- `src/whatsapp_chat_system/standalone_api.py` — 注册 personas router
- `src/whatsapp_chat_system/web_api.py` — legacy 注册 personas router + reply 注入 persona_id
- `src/whatsapp_chat_system/api/v1/__init__.py` — export
- `src/whatsapp_chat_system/api/internal/whatsapp_events.py` — None; standalone_api 已有 verify_internal_token helper
- `web/src/api.js` — 增加 V1 personas/contacts/persona 调用
- `web/src/components/ChatPane.jsx` — fetchPersonaCatalog 联后端，assignPersona 调用 V1
- `web/src/components/DiscoverPage.jsx` — 增加"AI 人设"分类卡展示内置人设（不含 GitHub/外部源字段）
- `web/src/i18n.js` — 4 语补齐人设 keys
- `web/src/styles.css` — 修复 PC 侧边栏 nav 视觉，AI 人设卡片样式

## 验收

1. `pytest -q tests/test_personas_api.py` 全部通过；
2. 全量 `pytest -q` 不 regress；
3. `npm run build` PASS；
4. `node --test web/tests/personaPlugins.test.js` PASS；
5. `node --test web/tests/*.test.js` 不 regress；
6. `git diff --check` PASS；
7. SDD/CHANGELOG/PROJECT_MEMORY/DECISIONS/TODO 同步。

## 步骤

### Step 1 — RED 后端

`tests/test_personas_api.py` 先写并确认失败：

```python
- GET /api/v1/personas unauthenticated 401
- GET /api/v1/personas authed returns known personas
- PUT /api/v1/personas/tong-jincheng/enable {enabled:true} persists
- PUT /api/v1/personas/{unknown}/enable 404
- PUT /api/v1/personas/default/enable 400
- PUT /api/v1/personas/professional-service/enable {enabled:false} persists
- PUT /api/v1/contacts/{jid}/persona {persona_id:"tong-jincheng"} writes
- PUT /api/v1/contacts/{jid}/persona {persona_id:"bogus"} 404
- repeat assign idempotent 200
```

运行 `pytest tests/test_personas_api.py -q` 期望失败。

### Step 2 — GREEN 后端

实现 `create_personas_router(runtime)`：
- `runtime.web_settings` 读写；
- `list_personas()` 静态元数据；
- 鉴权 `_is_authenticated(runtime, request)`（已有 helper）；
- 错误码标准化 `{code, message, retryable, request_id, details}` + `X-Request-ID`。

注册到 `standalone_api._build_standalone_app` 和 `web_api.build_app` 的 legacy 路径（仅用作开发）。

让 `/api/reply` 在 legacy 路径下读取 `reply_overrides['persona_id']`：

```python
overrides = reply_overrides or {}
persona_id = overrides.get("persona_id")
if not persona_id:
    contact_profiles = (config.web_settings or {}).get("contact_profiles") or {}
    contact_profile = contact_profiles.get(target.get("id")) or {}
    persona_id = contact_profile.get("persona_id")
```

透传到 rewriter。

### Step 3 — RED 前端

`web/tests/personaPlugins.test.js`：

```js
- fetchPersonaCatalog returns items + available true on 200
- fetchPersonaCatalog returns {items:[],available:false} on error
- assignPersona calls PUT /api/v1/contacts/<jid>/persona and stores persona
- assignPersona default clears selection
- enablePlugin calls PUT /api/v1/personas/{id}/enable
```

运行 `node --test web/tests/personaPlugins.test.js` 期望失败。

### Step 4 — GREEN 前端

`web/src/api.js`：
- `getPersonas()` → `GET /api/v1/personas`
- `enablePersonaPlugin(id, enabled)` → `PUT /api/v1/personas/{id}/enable`
- `assignPersonaToContact(jid, personaId)` → `PUT /api/v1/contacts/{jid}/persona`

`ChatPane.jsx`：
- 替换 fetchPersonaCatalog（已有 stub）调用真实 V1；
- assignPersona 调用真实 V1。

`DiscoverPage.jsx`：
- 新增"AI 人设"分类卡展示 list_personas()；
- 卡片：name / description / accent / 当前启用状态；
- 严禁显示任何外部源/仓库字段。

`web/src/styles.css`：
- 修复 `@media (min-width: 900px)` 与 `@media (min-width: 768px)` 之间 nav 视觉丢失；
- `.wx-sidebar-nav` 在小屏（768-900）增加 `flex: 0 0 64px`，确保不被压扁；
- `.wx-shell-content` 保持 `flex-direction: row`。

### Step 5 — 全量门禁

- `./.venv/bin/pytest -q`
- `npm run build`
- `node --test web/tests/*.test.js`
- `git diff --check`

### Step 6 — 文档

- CHANGELOG：+1 行"2026-07-12 受控 AI 人设 P0（Implemented，未切流）"
- PROJECT_MEMORY：+1 行当前状态
- DECISIONS：+1 行 2026-07-12 决策
- TODO：标 SDD-P0-08 In Progress

## 安全/边界

- 不远程加载任何 prompt；
- 不显示任何 GitHub/外部源信息；
- 不自动建表；persona 状态写 web_settings JSON；
- 切流由 MIG 阶段执行，不在本任务范围。
