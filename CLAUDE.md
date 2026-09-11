# CLAUDE.md — WhatsApp Chat System Agent Guide

## 项目概述

WhatsApp 多账号客服工作台。代码层面已迁移为独立系统；生产切流按既有迁移清单单独推进：

- **当前运行时（Standalone）**：独立 FastAPI 控制面（`standalone_api.py`）+ 独立业务库
  （SQLite 或 PostgreSQL）+ 进程内 Worker + 多账号 Baileys Bridge V2（`bridge/`）+ React SPA；
  不加载任何外部 profile / gateway / `state.db`；
- **Legacy（仅回滚/诊断）**：`web_api.py` + profile runtime，入口已从 CLI 移除，
  详见 `docs/DEPLOYMENT.md`；
- **AI**：直连 `https://wendingai.future1.us/v1`，默认模型 `gpt-5.3-codex-spark`；
- **权威规格**：`docs/sdd/`，所有后续开发必须严格按 SDD 执行。

当前线上地址：`http://127.0.0.1:8792`。前端可两种形态：由 FastAPI 以 `--web-dist`
单进程挂载 `web/dist`，或独立部署并通过 `VITE_API_BASE_URL` 直连 API。

## 核心路径

```
workspace:     /home/young11/workspace/whatsapp-chat-system-hermes/
后端代码:       /home/young11/workspace/whatsapp-chat-system-hermes/src/whatsapp_chat_system/
前端源码:       /home/young11/workspace/whatsapp-chat-system-hermes/web/src/
前端构建产物:   /home/young11/workspace/whatsapp-chat-system-hermes/web/dist/
线上后端:      /home/young11/workspace/whatsapp-chat-system-hermes/.venv/bin/python
```

## 启动命令（重要）

> **注意**：`cli.py` 的 `serve` 子命令只接受 `--host` / `--port` / `--web-dist`，
> **没有 `--profile`**（该参数仅存在于 router / forward / refresh-memory 三个 legacy 子命令）。
> 历史文档里的 `cli --profile ... serve` 写法已失效，会因无法识别的参数直接退出。

```bash
cd /home/young11/workspace/whatsapp-chat-system-hermes

# 首次启动需要（≥12 位；初始化完成后可从环境移除）
export CHAT_SYSTEM_BOOTSTRAP_PASSWORD='...'
export DATABASE_URL='postgresql://user:pass@127.0.0.1:5432/whatsapp_chat'
export WHATSAPP_BRIDGE_INTERNAL_TOKEN='...'

# 推荐：跨平台启动器（自动载入 .env、可自检、可先迁移）
.venv/bin/python scripts/run_server.py --check      # 只自检，不启动
.venv/bin/python scripts/run_server.py --migrate    # 先 alembic upgrade head 再启动

# 等价 CLI 写法（纯 API 模式；加 --web-dist 则为单进程托管前端）
.venv/bin/python -m whatsapp_chat_system.cli serve --host 127.0.0.1 --port 8792

# 前端构建
cd /home/young11/workspace/whatsapp-chat-system-hermes/web && npm run build

# 线上部署命令（构建后重启）
sudo fuser -k 8792/tcp 2>/dev/null
sudo nohup /home/young11/workspace/whatsapp-chat-system-hermes/.venv/bin/python \
  -m whatsapp_chat_system.cli serve \
  --host 127.0.0.1 --port 8792 \
  --web-dist /home/young11/workspace/whatsapp-chat-system-hermes/web/dist \
  >> /tmp/whatsapp-live.log 2>&1
```

生产环境变量由 `/etc/whatsapp-chat-system/api.env` 提供、systemd 单元注入。
单元文件在 `deploy/systemd/`：`whatsapp-chat-system.service`（单进程，含 `--web-dist`）
与 `whatsapp-chat-system-api-only.service`（纯 API，前端独立部署）。

## 验证命令

```bash
# 后端健康检查
curl http://127.0.0.1:8792/api/health

# 前端 JS 是否正确加载（关键验证）
curl -I http://127.0.0.1:8792/assets/index-*.js

# 全流程验证
curl http://127.0.0.1:8792/          # → 200 text/html
curl http://127.0.0.1:8792/assets/$(curl -s http://127.0.0.1:8792/ | grep -o 'assets/index-[^"]*\.js' | head -1 | cut -d/ -f2) -I | grep HTTP

# 内部事件接口必须先鉴权（期望 401，而非 422 或 200）
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8792/internal/events/whatsapp \
  -H 'Content-Type: application/json' -d '{"event_id":"probe"}'
```

## 测试命令

```bash
pytest -q                      # 后端（当前 354 passed, 7 skipped）
npm run web:test               # 前端 node:test（当前 124 passed）
npm run bridge:test            # Bridge node:test（当前 85 passed）
npm test                       # 前端 + Bridge

# PostgreSQL 专项（需可丢弃测试库；会 TRUNCATE 本项目使用的表）
TEST_DATABASE_URL='postgresql://user:pass@host:5432/whatsapp_test' \
  pytest tests/test_postgres_backend.py -v
```

## 每次任务前必读

1. `docs/sdd/README.md` — SDD 总纲和权威文档索引
2. 与任务相关的 `docs/sdd/*` — 需求、架构、数据、API、优化、开发流程、迁移
3. `docs/PROJECT_MEMORY.md` — 当前项目状态
4. `docs/TODO_AGENT.md` — 当前执行视图
5. `docs/CHANGELOG_AGENT.md` — 变更记录
6. `docs/DECISIONS.md` — 架构决策
7. `docs/STANDALONE-DEPLOYMENT.md` — 部署指南（三平台、分离/单进程、签名启用、验收清单）
8. `docs/DEPLOYMENT.md` — legacy 部署说明（仅回滚/诊断用）

未读取并确认相关 SDD 需求 ID，不允许开始业务代码修改。复杂任务必须先写 `docs/plans/YYYY-MM-DD-*.md`，并严格执行 RED → GREEN → REFACTOR、规格审查、代码质量审查和部署验证。

## 开发规范

新成员初始化开发环境与 Git hooks：

```bash
./scripts/setup-dev.sh
```

自动检查说明见 `docs/DEVELOPMENT_CHECKS.md`。

- **CSS 类命名**：`.wx-*` 前缀，所有 WeChat 设计 token 用 CSS 变量
- **i18n**：所有用户可见字符串必须用 `t('key')`，4个语言块 key 必须完全对齐
- **构建 gate**：`vite build` 与 `vite build --mode tauri` 必须通过；`pytest -q` 不得低于 354 passed；`npm run web:test` 不得低于 124；`npm run bridge:test` 不得低于 85
- **StaticFiles bug**：Starlette StaticFiles mount 到 `/assets` 时 URL strip prefix，directory 应指向 `dist/assets/` 而非 `dist/`

## 关键陷阱

1. **dist 未同步**：构建后必须重新部署到线上，不能假设 workspace = 线上
2. **StaticFiles path bug**：`app.mount('/assets', StaticFiles(directory=frontend_dist))` — directory 要用 `frontend_dist / 'assets'`
3. **端口占用**：`fuser -k 8792/tcp` 杀进程后再重启
4. **i18n key 错位**：sed 插入容易乱序，每次用 `grep -n "key:" i18n.js` 验证对齐
5. **SQLite 会静默忽略 `SELECT ... FOR UPDATE`**：不报错也不加锁。多进程抢占必须用带
   `status` 守卫的条件 UPDATE（CAS），见 `outbox.py`；`ai/job_repository.py` 用 dialect 分支处理
6. **前端 API 基址的权威变量是 `VITE_API_BASE_URL`**（SDD VCL-002），
   旧名 `VITE_API_BASE` 仅作兼容别名并打印弃用告警。`VITE_*` 全部是公开值，禁止放密钥
7. **FastAPI 依赖先于请求体校验执行**：鉴权放依赖里才能挡住未鉴权的畸形 payload（否则返回 422 会变成 schema 探测通道）。同一次请求的 nonce 不能被两层校验重复消费
8. **不要在持有数据库事务时调用 AI/网络**：一律「短事务读 → 无 session 调外部 → 短事务写」，参考 `ai/auto_reply_worker.py` 与 `translations_dispatcher.py`
9. **调整 `VITE_*` 环境变量名后要同步 `web/src/api.js` 的 `resolveApiBase`**，并有 `web/tests/apiBase.test.js` 守护

## Git

- GitHub: `https://github.com/sharefuture1/whatsapp-chat-system-hermes`
- 线上代码在 workspace，不在 `/root/whatsapp-chat-system/`
