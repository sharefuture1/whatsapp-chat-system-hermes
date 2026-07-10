# PROJECT_MEMORY.md — 项目状态快照

> 最后更新：2026-07-10 02:20 UTC

## 线上资源

- 后端地址：`http://127.0.0.1:8792`
- 前端 JS：`index-X_NsIE3q.js`（248740 bytes）
- 前端 CSS：`index-BWXtslEL.css`（43681 bytes）
- `/api/health`：200，`{"ok":true}`
- 首页、JS、CSS：均为 200
- 未认证 `/api/settings`：401（鉴权仍生效）
- CORS `OPTIONS /api/settings`：200

## 部署方式

FastAPI 直接挂载 Vite `web/dist`，生产前端与 API 共用 `127.0.0.1:8792`，不使用 Vite Preview。

```bash
cd /home/young11/workspace/whatsapp-chat-system-hermes/web
npm run build

sudo fuser -k 8792/tcp 2>/dev/null || true
sudo /home/young11/workspace/whatsapp-chat-system-hermes/.venv/bin/python \
  -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8792 \
  --web-dist /home/young11/workspace/whatsapp-chat-system-hermes/web/dist
```

## 本轮已修复

- 会话列表操作层默认隐藏，仅左滑后显示置顶/删除
- 左滑手势加入水平/垂直方向锁、单行展开、防误触
- SVG 图标显式使用 `currentColor`，避免图标消失
- 删除会话增加确认和失败反馈
- 前端补齐 `api.delete`
- CORS OPTIONS 预检绕过 session auth；普通 API 仍要求认证
- 普通发送和群发严格按后端真实 `success` 判断
- 失败消息显示错误状态，可重试错误支持原地重试
- 增量消息统一按 ID 游标排序，API 返回 `next_after_id` / `has_more`
- 前端连续拉取增量批次，避免超过 100 条时产生 gap
- 快速切换联系人时阻止旧请求覆盖新会话
- 移动端进入聊天后隐藏根 TabBar
- 输入框按 `scrollHeight` 自动增高、移动端 16px、支持底部安全区
- 中文输入法组合阶段 Enter 不发送
- 用户查看历史时新消息不强制滚底，显示“新消息”按钮
- 联系人抽屉 AI 风格入口不再错误关闭抽屉
- 四语言 i18n 键集合已对齐
- StaticFiles 测试在无 assets 目录的最小夹具下也可启动

## 测试状态

```text
pytest -q                             72 passed, 1 warning
npm run build                        PASS
node --test tests/chatSync.test.js   4 passed
python -m py_compile ...             PASS
git diff --check                     PASS
```

唯一警告为 FastAPI/Starlette TestClient 的上游弃用提醒，不影响运行。

## 环境

- 项目：`/home/young11/workspace/whatsapp-chat-system-hermes`
- Python venv：`/home/young11/workspace/whatsapp-chat-system-hermes/.venv`
- Hermes profile：`/root/.hermes/profiles/whatsapp-support`
- GitHub：`https://github.com/sharefuture1/whatsapp-chat-system-hermes`

## SDD 开发规范（强制）

- 权威入口：`docs/sdd/README.md`。
- 所有需求、架构、数据/API 契约、优化清单、质量门禁和迁移计划均已进入 `docs/sdd/`。
- `AGENTS.md` 与 `CLAUDE.md` 已强制要求：先规格、需求 ID、TDD、双阶段审查、全量验证、再更新文档和部署。
- `TODO_AGENT.md` 仅显示当前执行状态，不再作为需求真源。
- 旧 `docs/SDD.md` 已标为 Deprecated；`docs/ARCHITECTURE.md` 只保留 Legacy 基线和目标架构摘要。

## 架构迁移目标（Phase 1 已实现，待生产验收）

- SDD-P0-01 已实现：AI 配置由独立 `AISettings` 从 `WENDING_AI_*` 环境变量加载，不再要求 Hermes `config.yaml`。
- `WendingAIProvider` 统一调用 `/v1/chat/completions`，仅对 429/5xx/timeout 有限重试，错误结构化且不泄露 API key。
- `AIService` 已实现联系人 override > 账号 AI Profile > 全局默认模型解析。
- Rewriter 的智能改写、手动翻译、自动翻译已全部通过 AIService/Provider。
- 部署前必须在服务端设置 `WENDING_AI_API_KEY`；未配置时 `/api/v1/ai/settings` 返回 `api_key_configured=false`，AI 请求返回结构化 `configuration_error`，不得读取或回退到旧 Hermes `config.yaml` 中的密钥。
- 后续迁移仍按：新库 → 独立 Bridge 单账号/多账号 → Worker → UI/历史迁移；生产仍保持 Legacy，未切换服务。

## 仍需关注

- P0：定时发送目前只保存配置，尚无真实执行 worker
- P1：会话未读仍需后端真实计数
- P1：通讯录仍复用会话数据，需独立联系人模型
- P1：翻译请求仍可能同步阻塞消息详情
- P1：群发需后台任务、限速、进度、取消和幂等
- P1：会话列表查询和 SQLite 索引仍需性能治理
- P1：认证应迁移 HttpOnly Cookie/服务端 token 哈希
- P2：补移动端 Playwright 主链路回归测试
- P3：真实 WhatsApp 环境继续调查少数历史消息同步 gap
