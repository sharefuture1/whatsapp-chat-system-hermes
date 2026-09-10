# 2026-09-11 API readiness 与 Web/Tauri transport 拆分

## Objective

补齐 Standalone API 的 live/readiness 健康探针，并让浏览器主包不再静态加载 Tauri HTTP transport；保持 `whats.wending.ai` API-only 边界、Tauri 最小权限和现有浏览器 API 行为不变。

## Requirement IDs

- NFR-OPS-002：live/readiness health checks
- VCL-001：Vercel/Web 构建产物合同
- VCL-004：API 域 Nginx 运行契约
- SEC-DESKTOP-001：Tauri 最小网络权限
- QA-001：测试、构建与真实运行验证

## RED

1. `tests/test_standalone_runtime.py` 要求 `/health/live` 200，`/health/ready` 在 ready 时 200、非 ready 时 503；旧实现应 404。
2. `web/tests/api.test.js` 要求 `api.js` 不得顶层静态 import `@tauri-apps/plugin-http`，必须动态 import；旧实现应失败。

## GREEN

1. Standalone API 增加 `/health/live` 与 `/health/ready`，保留 `/api/health` 聚合诊断。
2. Nginx 仅公开两个精确 health 路径，不放宽 `/internal/*`。
3. `api.js` 缓存 Tauri HTTP 模块动态加载 Promise；Browser 始终走 `globalThis.fetch`。
4. 更新 Tauri validator，禁止静态 plugin-http import。

## Gates

- focused Python health test
- `npm run web:test`
- `npm run bridge:test`
- `npm run tauri:validate`
- Vercel Production build
- Tauri build
- Python regression groups
- Ruff + `git diff --check`
- public `https://whats.wending.ai/health/live` / `health/ready`

## Rollback

- 后端可回退到上一 commit 并保留 `/api/health`；Nginx 删除两个精确 health location 即可。
- 前端可恢复静态 Tauri import，不影响 API 数据模型或数据库。
