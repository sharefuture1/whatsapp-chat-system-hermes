# PROJECT_MEMORY.md — 项目状态快照

> 最后更新：2026-07-10 07:10 UTC

## 当前结论

项目**尚未彻底从 Hermes 分离**：

- AI Provider 和账号级业务数据库已独立。
- 多账户控制面 API、Bridge HTTP Client 契约、微信式账号中心 UI 已落地。
- 生产读取消息/会话和启动参数仍依赖 Legacy Hermes profile/state；独立 Node/Baileys Bridge V2、事件接收、Outbox Worker 和历史切换尚未完成。
- 账号中心不会伪造在线或二维码；Bridge V2 未安全配置时写操作返回结构化 `bridge_not_configured`，并补偿删除未成功注册的账号记录。

## 线上资源

- 后端地址：`http://127.0.0.1:8792`
- 前端 JS：`index-BN8XBbSa.js`
- 前端 CSS：`index-CdAyXNbe.css`
- `/api/health`：200
- 新 JS 资源：200
- 未认证 `/api/v1/accounts`：401
- 生产仍以 `/root/.hermes/profiles/whatsapp-support` 提供 Legacy 消息数据，属于迁移期兼容，不代表完成分离。

## 本轮实现

- SDD-P0-03/P1-01 实施计划：`docs/plans/2026-07-10-bridge-v2-account-center.md`。
- 新增账号 repository/service，所有账号业务通过独立 SQLAlchemy Session。
- 新增 `GET/POST/PATCH/DELETE /api/v1/accounts` 以及 connect/qr/logout 操作。
- 新增只允许 loopback 的 Bridge Client，带超时、结构化错误和安全响应。
- 未配置内部 Bridge token 时 fail-closed，不使用可预测默认密钥。
- Bridge 注册失败会补偿删除数据库账号；停用账号先停止 Bridge，再提交 `enabled=false`。
- 新增迁移 `0002_ai_runtime_timeout_retry.py`，修复 AI runtime timeout/retry ORM 与迁移漂移。
- 前端新增“我 → WhatsApp 账号”账号中心、账号列表/详情/状态/删除确认/二维码页面。
- 用户可见设置页已移除 Hermes profile、profile path 和 CLI 命令入口。
- 四语言补齐账号中心文案；默认新账号 `auto_reply_mode=off`。

## 验证状态

```text
pytest -q                         106 passed, 1 warning
node --test web/tests/*.test.js  9 passed
npm run build                    PASS
git diff --check                 PASS
Alembic upgrade→downgrade→upgrade PASS
/api/health                      200
/assets/index-BN8XBbSa.js        200
unauth /api/v1/accounts          401
```

唯一警告是 FastAPI/Starlette TestClient 上游弃用提醒。

## 下一阶段阻断

- 实现独立 Node/Baileys Bridge V2：真实 QR、每账号 session、状态、收发、媒体和回执。
- 实现 `/internal/events/whatsapp` 幂等事件接收与 account 状态落库。
- 完成 A/B 多账号隔离、断线恢复和删除 session 真实验证。
- 将消息读取/发送迁移到独立数据库和 Outbox Worker。
- 完成 Legacy 只读迁移与最终停止 Hermes gateway/profile/state 依赖。

## 环境

- 项目：`/home/young11/workspace/whatsapp-chat-system-hermes`
- Python venv：`/home/young11/workspace/whatsapp-chat-system-hermes/.venv`
- GitHub：`https://github.com/sharefuture1/whatsapp-chat-system-hermes`
- 生产端口：`127.0.0.1:8792`

## SDD 开发规范

- 权威入口：`docs/sdd/README.md`。
- 需求/架构/API/优化状态只能在 SDD 中修改。
- 按 requirement ID、计划、RED→GREEN→REFACTOR、双阶段审查、全量门禁、真实部署验证执行。
