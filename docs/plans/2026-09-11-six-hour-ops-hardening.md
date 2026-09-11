# 2026-09-11 六小时优化轮次：静态缓存与 systemd 沙箱

## Objective

在不改变业务功能和数据模型的前提下，优化 `whats.wending.ai` 自托管前端的缓存策略，并收紧 FastAPI / Bridge systemd 服务的文件系统和内核攻击面。

## Requirement IDs

- VCL-006：带 hash 的前端静态资源必须长期 immutable 缓存，`index.html` 必须 no-cache。
- NFR-OPS-001：生产服务由受控 systemd 单元运行。
- SEC-002：Bridge 仅允许必要的内部运行边界，不扩大主机权限。
- QA-001：部署契约、测试与真实生产验证。

## RED

1. 扩展部署契约测试，要求 API / Bridge unit 使用 `ProtectSystem=strict`、`ProtectHome=true`、`PrivateDevices=true`、`RestrictSUIDSGID=true`、`ProtectKernelTunables=true`、`ProtectKernelModules=true`、`ProtectControlGroups=true`、`LockPersonality=true`，并仅对各自 `/var/lib/whatsapp-chat-system/*` runtime 开放写权限。
2. 增加 Nginx 静态缓存契约测试，要求 `/assets/` 返回 `public, max-age=31536000, immutable`，`index.html` 返回 `no-cache`。
3. 运行 focused tests，确认旧配置 RED。

## GREEN

1. 更新 `deploy/systemd/whatsapp-chat-system.service`、`whatsapp-chat-system-api-only.service`、`whatsapp-bridge-v2.service`。
2. 更新 `deploy/nginx/whats.wending.ai.conf`。
3. focused tests 全绿。

## Deploy / Verify

- 同步 systemd 与 Nginx 到 gcptw 生产。
- `systemd-analyze security` 对比风险暴露。
- `nginx -t` 通过后 reload。
- API / Bridge 重启后均 active。
- `/health/live`、`/health/ready`、`/api/health` 均 200。
- hash JS/CSS 响应包含 immutable；`/` 与 `/index.html` no-cache；`/internal/*` 仍 404。
- 若任一服务无法启动，立即恢复上一版 unit/config。

## Git

提交到 `codex/p0-hardening-tauri2`；不得提交任何密码、token、session、runtime 文件或服务端密钥。
