# AI 回复与翻译网页同步修复计划

> 状态：In Progress。关联 `SDD-P1-05`、`SDD-P1-10`、`NFR-PERF-002`、`NFR-REL-002`。

## 根因

1. Legacy 同会话 delta 请求共用“最新请求获胜”tracker；慢请求可能被下一轮轮询判旧，导致返回 200 但不进入 React，游标长期不推进。
2. Legacy delta GET 在响应前同步生成缺失译文，扩大慢请求与饥饿窗口。
3. 翻译写入旁路缓存，不改变消息 ID；`after_id` 无法表达旧消息字段更新。
4. `mergeNewMessages` 只追加新 ID，不 upsert 相同 ID 的 `translated/lang`。
5. V2 消息 API不挂载 Legacy 翻译缓存；周期完整刷新会用无译文服务端对象覆盖本地译文。

## 目标行为

- 同一 Legacy 会话最多一个 delta drain；新 tick 只合并为一次补跑，不废弃当前响应。
- 会话切换仍必须取消/拒绝旧会话响应。
- delta GET 只返回消息和已有翻译缓存，不同步调用模型。
- 相同 message ID 的服务端更新可合并 `translated/lang/content/status/platform_message_id`，同时保留必要的本地 optimistic 状态。
- V2 完整刷新不得清除当前客户端已经成功得到的译文。
- Legacy 新 AI assistant 消息必须在下一次成功 delta 后出现并推进 cursor。

## TDD 任务

1. Web RED：同 ID upsert 翻译、V2 refresh 保留本地译文、同会话 delta single-flight/coalescing 源码契约。
2. Python RED：delta endpoint 不调用翻译 Provider，只读取已有缓存；完整 Legacy API仍挂载已有缓存。
3. 最小实现前端 merge 和 delta 调度。
4. 最小实现后端 cache-only attach 模式。
5. Focused tests → Web/Python/Bridge 全量 → 双视口浏览器 → 生产验证。

## 后续架构

跨客户端实时同步旧消息字段需要 translation revision/event cursor 或 SSE/WebSocket `translation.completed`。本轮先确保单客户端稳定、刷新不丢、重进可恢复，并消除请求饥饿。
