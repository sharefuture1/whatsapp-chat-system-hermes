# Architecture

> 权威架构规格：[`docs/sdd/02-system-architecture.md`](./sdd/02-system-architecture.md)
>
> 数据模型：[`docs/sdd/03-data-model.md`](./sdd/03-data-model.md)
>
> API/事件：[`docs/sdd/04-api-and-events.md`](./sdd/04-api-and-events.md)

## Current Production: Legacy

当前生产仍采用过渡架构：

1. Hermes profile runtime 提供 WhatsApp gateway、单账号 Bridge 和 `state.db`；
2. Python FastAPI 读取 Legacy 数据并提供 API；
3. React 管理台由 FastAPI 挂载构建产物；
4. 当前后端监听 `127.0.0.1:8792`，Bridge 监听 `127.0.0.1:3000`。

这只是当前运行基线，不是未来目标架构。

## Approved Target: Standalone

目标架构为：

```text
React UI
  → FastAPI Control Plane
  → PostgreSQL + Redis + Background Worker
  → Independent Multi-account Baileys Bridge
  → WhatsApp

FastAPI AI Orchestrator
  → https://wendingai.future1.us/v1
  → gpt-5.3-codex-spark
```

关键要求：

- 不依赖 Hermes CLI、profile、gateway 或 Hermes `state.db`；
- 每个 WhatsApp 账号独立 socket、session、状态、重连和限速；
- 所有联系人、会话、消息和任务带 `account_id`；
- 发消息通过 Outbox/Worker；
- 定时和群发由真实 Worker 执行；
- Bridge 事件通过幂等 webhook 进入业务数据库；
- 旧 Hermes 数据仅由只读 importer 迁移。

任何架构变更必须先修改 `docs/sdd/` 和 `docs/DECISIONS.md`。
