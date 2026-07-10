# PROJECT_MEMORY.md — 项目状态快照

> 最后更新：2026-07-10 10:50 UTC

## 当前结论

项目**尚未彻底从 Hermes 分离**，但独立 Bridge V2 的代码链路已进入 `Implemented`：

- AI Provider、账号级业务数据库已独立。
- 多账户控制面 API、Bridge HTTP Client、微信式账号中心 UI 已落地。
- 独立 Node/Baileys Bridge V2 已实现账号级 session/socket、QR、状态、重连、发送和回执事件。
- 持久化 FileSpool/EventSink 与 FastAPI `/internal/events/whatsapp` 幂等事务接收已实现。
- 生产仍使用 Legacy `127.0.0.1:3000` 和 Hermes profile/state 提供现有消息链；V2 仅在 `127.0.0.1:3100` 完成无真实账号的安全影子验证，尚未切流。
- 真实扫码、真实收发、双账号同时在线、历史迁移、Outbox Worker 与 Hermes shutdown 尚未验收。
- Legacy 网页直发同步缺口已修复：只有 Bridge 明确成功后才将 outbound assistant 消息和 WhatsApp ID 写回 `state.db`；页面刷新/增量不会再丢失成功气泡。

## 线上与影子状态

- FastAPI：`http://127.0.0.1:8792`，health 200。
- 前端：`index-CZeVLI8-.js` / `index-CdAyXNbe.css`，本机 FastAPI 资源 200；公网域名当前被 Cloudflare `525` 阻断，待修复边缘 TLS 后复验。
- Legacy Bridge：`127.0.0.1:3000`，保持运行。
- Bridge V2 影子：曾在 `127.0.0.1:3100` 启动并验证 live/ready、认证、create/status/stop；验证后已停止并清理临时 token/runtime。
- 生产仍传入 `/root/.hermes/profiles/whatsapp-support`，属于迁移期兼容。

## 本轮实现：Task 5 + Task 6

### Bridge V2

- 新增 `bridge/` 独立 Node 进程，Baileys 锁定 `6.7.22`。
- AccountManager 按 `account_id` 隔离 session/socket/spool/media。
- 每账号连接互斥、socket generation、指数退避+jitter、stop/logout/delete 语义和生命周期串行化。
- loopback/Host/token/request-id/HTTP timeout/live-ready/优雅关闭安全门禁。
- QR `qr_data_url`、稳定过期语义；定时器或读取触发过期均发送 offline 事件。
- 发送必须获得真实 WhatsApp message ID；回执产生 sent/delivered/read/failed 事件。
- 状态 API 和 account.error 只返回稳定脱敏文案，不暴露路径、token 或底层异常。

### 可靠事件链

- FileSpool 先原子落盘再 POST，账号目录 `0700`。
- pending/inflight/dead、崩溃恢复、指数退避、422 dead-letter、500/timeout/401 保留重试。
- 每账号 sequence 持久化单调；按 sequence/入队顺序 claim。
- 重启自动扫描并 replay spool；同账号只保留一个 EventSink owner。
- 同 event_id 会比较 canonical envelope；不一致显式 identity conflict，不静默吞事件。
- FastAPI 内部事件接口使用常量时间 token 校验、结构化错误和 request ID。
- Receiver 支持 account 状态、message.upsert、sent/delivered/read/failed；按 `(account_id,event_id)` 幂等并校验 payload hash。
- message/contact/conversation/event 同事务落库，状态与回执单调，不跨账号。
- Alembic `0003` 补充 sequence、payload_hash、消息时间字段及旧事件 hash 回填；downgrade 跨账号 event ID 冲突会明确中止。

## 验证状态

```text
pytest -q                          119 passed, 1 warning
bridge npm test                   63 passed
bridge npm run lint               PASS
bridge npm audit --omit=dev       0 vulnerabilities
web node --test tests/*.test.js   9 passed
web npm run build                 PASS
Alembic upgrade→downgrade→upgrade PASS
git diff --check                  PASS
FastAPI /api/health               200
Legacy web reply sync probe       PASS (real WhatsApp ID + local ID + delta API)
V2 shadow live/ready              200
V2 unauth API                     401
V2 create/status/stop             200
```

唯一警告是 FastAPI/Starlette TestClient 上游弃用提醒。

## 下一阶段阻断

1. 用测试 WhatsApp 账号完成真实扫码、session 重启恢复、入站消息、出站真实 message ID 和回执验收。
2. 启动第二账号，完成 A/B 同时在线、断线/登出/删除互不影响验收。
3. 将账号控制面安全配置到 Bridge V2 3100，并保持 Legacy 3000 可回滚。
4. 完成 Outbox Worker 和发送路径切换。
5. 只读导入 Legacy 数据、影子比对、最终停止 Hermes gateway/profile/state 依赖。

## 环境

- 项目：`/home/young11/workspace/whatsapp-chat-system-hermes`
- Python venv：`/home/young11/workspace/whatsapp-chat-system-hermes/.venv`
- GitHub：`https://github.com/sharefuture1/whatsapp-chat-system-hermes`
- 生产端口：`127.0.0.1:8792`

## SDD 开发规范

- 权威入口：`docs/sdd/README.md`。
- 需求/架构/API/优化状态只能在 SDD 中修改。
- 按 requirement ID、计划、RED→GREEN→REFACTOR、双阶段审查、全量门禁、真实部署验证执行。
