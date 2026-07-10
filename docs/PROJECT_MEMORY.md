# PROJECT_MEMORY.md — 项目状态快照

> 最后更新：2026-07-09 14:42 UTC

## 线上资源

| 资源 | 值 |
|------|-----|
| 后端地址 | `http://127.0.0.1:8792` |
| 前端 JS | `index-DtN9hy5s.js` (235KB) |
| 前端 CSS | `index-CJfNWq4L.css` (42KB) |
| health | `{"ok":true}` ✅ |
| JS 加载 | ✅ 200 OK |
| CSS 加载 | ✅ 200 OK |

## 部署方式

**FastAPI 直接挂载 SPA**（非 nginx 代理）

```bash
# 构建
cd /home/young11/workspace/whatsapp-chat-system-hermes/web && npm run build

# 部署
sudo fuser -k 8792/tcp 2>/dev/null
sudo nohup /home/young11/workspace/whatsapp-chat-system-hermes/.venv/bin/python \
  -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8792 \
  --web-dist /home/young11/workspace/whatsapp-chat-system-hermes/web/dist \
  >> /tmp/whatsapp-live.log 2>&1
```

## 已知已修复的 Bug（参考）

| Bug | 状态 | 修复版本 |
|-----|------|---------|
| StaticFiles `/assets` 返回 404 | ✅ 已修复 | index-DtN9hy5s.js |
| mobile ChatPane 高度坍塌 | ✅ 已修复 | index-CJfNWq4L.css |
| pinned 置顶逻辑失效 | ✅ 已修复 | App.jsx |
| ChatList 设置按钮 PlusIcon | ✅ 已修复 | ChatList.jsx |
| 新消息不自动滚底 | ✅ 已修复 | ChatPane.jsx |
| i18n key 错位 | ✅ 已修复 | i18n.js |

## 当前测试状态

```
pytest -q → 43 passed, 1 failed
```

失败的测试是 `test_all_t_keys_exist_in_dict`（60+ 缺失 i18n keys，早期遗留）。

## 后端日志

```
/tmp/whatsapp-live.log
```

## 环境

- Python venv: `/home/young11/workspace/whatsapp-chat-system-hermes/.venv/`
- Hermes profile: `/root/.hermes/profiles/whatsapp-support/`
- GitHub repo: `https://github.com/sharefuture1/whatsapp-chat-system-hermes`

## 当前待关注问题

| 优先级 | 问题 |
|--------|------|
| P2 | ContactsPage 搜索功能刚加，需验证 |
| P2 | Settings platforms tab CSS 部分缺失 |
| P3 | 消息同步 gap（部分聊天记录未拉取） |
