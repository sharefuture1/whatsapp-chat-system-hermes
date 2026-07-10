# CLAUDE.md — WhatsApp Chat System Agent Guide

## 项目概述

WhatsApp 客服工作台（Hermes Messaging Operations Console）。三层架构：
1. **Hermes profile runtime** — WhatsApp gateway + state.db
2. **Python FastAPI 后端** — 读 Hermes 状态，暴露安全 API
3. **React 操作员 UI** — 会话列表、聊天、设置

**线上地址**：`http://127.0.0.1:8792`（后端），前端直接由后端 FastAPI 挂载 `web/dist`

## 核心路径

```
workspace:     /home/young11/workspace/whatsapp-chat-system-hermes/
后端代码:       /home/young11/workspace/whatsapp-chat-system-hermes/src/whatsapp_chat_system/
前端源码:       /home/young11/workspace/whatsapp-chat-system-hermes/web/src/
前端构建产物:   /home/young11/workspace/whatsapp-chat-system-hermes/web/dist/
线上后端:      /home/young11/workspace/whatsapp-chat-system-hermes/.venv/bin/python
```

## 启动命令（重要）

```bash
# 后端（开发/调试用）
cd /home/young11/workspace/whatsapp-chat-system-hermes
./.venv/bin/python -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8792

# 前端构建
cd /home/young11/workspace/whatsapp-chat-system-hermes/web && npm run build

# 线上部署命令（构建后重启）
sudo fuser -k 8792/tcp 2>/dev/null
sudo nohup /home/young11/workspace/whatsapp-chat-system-hermes/.venv/bin/python \
  -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8792 \
  --web-dist /home/young11/workspace/whatsapp-chat-system-hermes/web/dist \
  >> /tmp/whatsapp-live.log 2>&1
```

## 验证命令

```bash
# 后端健康检查
curl http://127.0.0.1:8792/api/health

# 前端 JS 是否正确加载（关键验证）
curl -I http://127.0.0.1:8792/assets/index-*.js

# 全流程验证
curl http://127.0.0.1:8792/          # → 200 text/html
curl http://127.0.0.1:8792/assets/$(curl -s http://127.0.0.1:8792/ | grep -o 'assets/index-[^"]*\.js' | head -1 | cut -d/ -f2) -I | grep HTTP
```

## 每次任务前必读

1. `docs/PROJECT_MEMORY.md` — 当前项目状态、最新部署哈希、已知问题
2. `docs/TODO_AGENT.md` — 待办任务
3. `docs/CHANGELOG_AGENT.md` — 变更记录
4. `docs/DECISIONS.md` — 架构决策
5. `docs/DEPLOYMENT.md` — 部署文档

## 开发规范

- **CSS 类命名**：`.wx-*` 前缀，所有 WeChat 设计 token 用 CSS 变量
- **i18n**：所有用户可见字符串必须用 `t('key')`，4个语言块 key 必须完全对齐
- **构建 gate**：`vite build` 必须通过；`pytest -q` 保持 44+ passed
- **StaticFiles bug**：Starlette StaticFiles mount 到 `/assets` 时 URL strip prefix，directory 应指向 `dist/assets/` 而非 `dist/`

## 关键陷阱

1. **dist 未同步**：构建后必须重新部署到线上，不能假设 workspace = 线上
2. **StaticFiles path bug**：`app.mount('/assets', StaticFiles(directory=frontend_dist))` — directory 要用 `frontend_dist / 'assets'`
3. **端口占用**：`fuser -k 8792/tcp` 杀进程后再重启
4. **i18n key 错位**：sed 插入容易乱序，每次用 `grep -n "key:" i18n.js` 验证对齐

## Git

- GitHub: `https://github.com/sharefuture1/whatsapp-chat-system-hermes`
- 线上代码在 workspace，不在 `/root/whatsapp-chat-system/`
