# 2026-07-18 SDD-P0-10 性能快赢包实施

> 规格：`docs/sdd/09-performance-and-realtime.md`
> 范围：PERF-001/002/003/006/008 + ChatList 骨架屏（UI）
> 注：PERF-005（SQLite WAL/busy_timeout）已由上游 main 落地，本轮只更新状态。

## 实施项

### 后端

1. **PERF-003 AI Provider/Rewriter 单例**
   - `api/v1/messages.py` 翻译端点：Rewriter 缓存到 `app.state.translation_rewriter`，
     不再每请求新建（每次新建 = 新 Provider = 新 TLS 连接）。
   - `translations_dispatcher.py`：`_rewriter()` 实例级缓存。
   - 翻译端点的 AI 调用移出 DB session（读缓存/消息 → 关 session → AI → 新 session 写回）。
2. **PERF-006 AutoReplyWorker 事务隔离**
   - `_process` 拆三段：短事务（start + 校验 + 读上下文）→ 无 session 调 AI →
     新短事务（重校验人工回复竞态 + enqueue outbox + complete，version CAS 保持）。

### 前端

3. **PERF-001 刷新调度**：`App.jsx` 去掉 `Math.max(30,…)`；间隔钳 [3,300]，缺省/非法默认 5s，不再解释为关闭。
4. **PERF-002 轮询减负**：conversations `limit` 200→50；contacts 拆出常规轮询
   （仅登录初始化、进入通讯录 Tab、显式刷新时拉取）；conversations 与 dashboard 保持 Promise.all。
5. **PERF-008 渲染与缓存稳定**：
   - `mergeFreshMessages` 数据等价时返回原数组引用；
   - `saveConversationCache` 改 idle 调度（requestIdleCallback / setTimeout 降级）；
   - ChatPane 去掉"缓存 5 分钟内新鲜则跳过网络"的短路，缓存仅作首屏骨架 + 并行网络校验。
6. **UI**：ChatList 首次加载骨架屏（复用 `.wx-skeleton` token）；列表项过渡打磨。

## TDD

- RED：
  - `tests/test_translation_singleton.py`：两次翻译请求只构造一次 Rewriter；AI 调用期间无打开 session。
  - `tests/test_auto_reply_worker.py`：注入 Provider 断言 chat() 时 open session 数为 0；
    AI 调用期间出现人工回复 → 取消且不入 Outbox。
  - `web/tests/perfQuickWins.test.js`：无 `Math.max(30`；limit=50；轮询路径无 contacts 请求；
    merge 引用稳定；缓存 idle 写；无新鲜短路；ChatList 骨架。
- GREEN：实现上述改动，全量 pytest / web / bridge / build 通过。

## 明确不做（本轮）

- `updated_since` 增量参数（并入 SDD-P1-12 与 SSE 同期实现）；
- PERF-004 剩余（批量翻译 DB 真源上游已在推进）；PERF-007 索引迁移（独立迁移任务）。
