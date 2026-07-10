# DECISIONS.md — 架构决策记录

## 2026-07-09: StaticFiles `/assets` mount path bug

**问题**：Starlette StaticFiles mount 到 `/assets` 时，URL path `/assets/index.js` 会被 strip `/assets` 前缀，然后查找 `directory/index.js`。但文件实际在 `dist/assets/index.js`，导致 404。

**决策**：mount 时 `directory` 参数指向 `frontend_dist / 'assets'`，而非 `frontend_dist`。

```python
# 错误（会导致 404）
app.mount('/assets', StaticFiles(directory=frontend_dist), name='web-assets')

# 正确
app.mount('/assets', StaticFiles(directory=frontend_dist / 'assets', check_dir=True), name='web-assets')
```

**涉及文件**：`src/whatsapp_chat_system/web_api.py`

---

## 2026-07-09: SPA serving 方案

**决策**：FastAPI 直接挂载 `web/dist`，不使用 nginx 静态文件服务。

**优点**：
- 单一进程，无需额外 web server
- `--web-dist` CLI 参数显式控制
- catch-all路由 `/{full_path:path}` 处理 SPA 路由

**验证**：
```
/api/* → FastAPI handlers
/assets/* → StaticFiles (dist/assets/)
/ → dist/index.html (catch-all)
```

---

## 2026-07-09: 前端 CSS 类名规范

**决策**：统一使用 `.wx-*` 前缀，避免与第三方库冲突。

设计 token：
- `--wx-brand`: 主品牌绿 `#07C160`
- `--wx-bg`: 背景 `#EDEDED`
- `--wx-surface`: 面板 `#F5F5F5`
- `--wx-text`: 主文字 `#1A1A1A`
- `--wx-text-secondary`: 次文字 `#888`
- `--wx-text-muted`: 弱文字 `#999`
- `--wx-border`: 分割线 `#E5E5E5`

组件类：
- `.wx-shell` / `.wx-shell-content` / `.wx-shell-header`
- `.wx-tab-bar` / `.wx-tab-btn`
- `.wx-list-item` / `.wx-avatar` / `.wx-badge`
- `.wx-bubble` / `.wx-composer`
- `.wx-skeleton` / `.wx-spinner`
- `.wx-modal` / `.wx-primary-btn`

---

## 2026-07-09: i18n 管理策略

**决策**：4 语言（en/zh/th/lo）全部对齐，所有 key 在 4 个 block 的行号严格对应。

**工具**：sed 精确行号插入（不依赖 patch 的字符串匹配）

**验证**：`grep -n "^    key:" i18n.js` 对齐所有 4 个 block

---

## 2026-07-08: pinned 状态来源

**决策**：pinned 列表使用后端 `/api/conversations` 返回的 `item.pinned` 布尔字段，不在前端维护独立 state。

前端仅维护 `Set<user_id>` 用于快速查找，pinned 分组直接从 conversations 列表 filter。
