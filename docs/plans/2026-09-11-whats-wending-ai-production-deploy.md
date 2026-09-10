# 2026-09-11 whats.wending.ai 生产域名与分离部署计划

## Objective

将 Standalone API 的正式公网域名迁移到 `https://whats.wending.ai`，保持 Vercel Web、Tauri 2 与自托管 FastAPI/Bridge 的同一 API 契约，并在 gcptw 上完成可回滚的生产部署与真实健康检查。

## Requirement IDs

- VCL-002：Vercel/Web API 基址
- VCL-003：CORS 与鉴权
- VCL-004：Nginx/SSE 代理兼容
- VCL-005：Production/Preview 环境隔离
- MIG-001：Standalone systemd 部署配置合同
- SEC-DESKTOP-001：Tauri 最小网络权限
- QA-001：构建、测试与真实运行门禁

## Files

### Modify

- `docs/sdd/10-frontend-vercel-deployment.md`
- `docs/sdd/11-tauri-desktop-distribution.md`
- `docs/sdd/02-system-architecture.md`
- `web/vite.config.js`
- `web/.env.production`
- `web/.env.tauri`
- `web/tests/apiBase.test.js` 或新增部署环境测试
- `src/whatsapp_chat_system/standalone_api.py`
- `src-tauri/tauri.conf.json`
- `src-tauri/capabilities/main.json`
- `scripts/validate-tauri.mjs`
- `deploy/nginx/whats.future1.us.conf`（迁移为新正式域名内容，文件名另行收敛）
- `docs/CHANGELOG_AGENT.md`
- `docs/PROJECT_MEMORY.md`
- `docs/TODO_AGENT.md`
- `docs/DECISIONS.md`

### Create

- `web/deploymentEnv.js`
- `web/tests/deploymentEnv.test.js`
- `deploy/nginx/whats.wending.ai.conf`

## RED

1. 新增部署环境测试：
   - Vercel Production 未配置 API base 时解析为 `https://whats.wending.ai/api`；
   - Vercel Preview 未配置时保持空值/相对路径；
   - Vercel Preview 显式配置生产 API 时拒绝构建；
   - staging/自定义 Preview API 可用。
2. 扩展 Tauri 静态验证，要求 CSP、HTTP capability、Tauri env 仅允许 `whats.wending.ai`。
3. 运行 focused tests，确认旧配置下 RED。

## GREEN

1. 实现 `deploymentEnv.js` 并接入 Vite config；Production 只注入公开的正式 API base，Preview fail-closed 防止误打生产。
2. 更新 Tauri CSP/capability/env 到 `whats.wending.ai`。
3. 更新 FastAPI 默认 CORS 来源与 Nginx 模板。
4. focused tests 全绿。

## REFACTOR / Full Gates

- `npm run tauri:validate`
- `npm run web:test`
- `npm run bridge:test`
- `npm run web:build`
- `npm run web:build:tauri`
- `.venv/bin/pytest -q`
- `git diff --check`
- secret scan / git status 检查

## Production deployment

1. 在 `/opt/whatsapp-chat-system` 安装当前目标 commit；运行目录放 `/var/lib/whatsapp-chat-system/{api,bridge}`。
2. 生成仅主机保存的 API/Bridge token、HMAC secret、AI encryption key、bootstrap password；不进入 Git。
3. SQLite 首次部署用于单机验证，执行 `alembic upgrade head`；后续可无停机迁移到 PostgreSQL。
4. API 只监听 `127.0.0.1:8792`；Bridge 只监听 `127.0.0.1:3100`。
5. Nginx `whats.wending.ai` 仅代理 `/api/` 与需要的内部 Web 路径；SSE 路径关闭 buffering，超时 >=300s；`/internal/` 不对公网暴露。
6. 为 `whats.wending.ai` 获取/安装正确 TLS 证书，不复用不含该 SAN 的旧证书。
7. 验证：
   - API `/api/health` 200
   - Bridge `/health/live`、`/health/ready` 200
   - `/internal/events/whatsapp` 外网不可达/本机未鉴权 401
   - CORS allowlist 正确
   - `https://whats.wending.ai/api/health` 200
   - Cloudflare 不再 525
   - 日志无启动异常

## Rollback

- 保留现有 `image.wending.ai` Nginx/service 不修改。
- 新服务失败时禁用新 Nginx site/systemd unit，恢复旧默认站点行为；保留新 SQLite/runtime/spool 现场。
- 不在本轮停止任何仍存在的 Legacy WhatsApp 处理链，除非明确验证同账号不会双发。
