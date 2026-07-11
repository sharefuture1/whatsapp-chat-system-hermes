# AnalysisJobRepository 高并发审查 RED 摘要

日期：2026-07-11
关联：DATA-007、FR-CON-005..010、FR-PLG-005..006

在实现前增加/更新回归测试，覆盖：

- PostgreSQL aware UTC 与 SQLite naive UTC 时间适配；claim/recovery SQL 的 `FOR UPDATE SKIP LOCKED`、账号和预算过滤。
- worker 状态 CAS 显式 `account_id`、精确 lease expiry 边界、父任务取消后拒绝 worker 结果。
- 幂等请求 immutable identity（hash/type/scope/调度预算）、输入及进度参数校验。
- enqueue queue backpressure、claim active/budget backpressure。
- 父取消仅传播 pending/retry children，不强抢 claimed/running lease；父已取消/终态后禁止 enqueue/claim，过期 leased child recovery 直接 cancelled。
- global claim 在 SQL 候选内以 correlated active count 跳过达到 per-account 上限的账号，避免头部账号阻塞其他账号。
- PostgreSQL parent generation 通过 parent row `FOR UPDATE` 与 cancel/child transition 同锁序列化；committed wrapper 在 commit 后不再执行可失败 ORM 操作。
- committed claim wrapper 返回 immutable DTO，且另一 Session 立即可见。
- recovery account 分片与有界 limit。

首次 focused RED（旧实现）：新增接口/语义缺失；原基线测试随后因 worker API 增加 account_id 需要同步更新。实现过程中的首轮执行为 `6 failed, 1 passed`（enqueue 构造重复参数），确认测试能捕获回归后进入 GREEN。
