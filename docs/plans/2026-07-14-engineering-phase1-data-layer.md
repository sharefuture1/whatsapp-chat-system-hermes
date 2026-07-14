# 工程化重构 Phase 1：前端数据层与同步边界

## Objective
将当前可运行原型收敛为可维护的工程系统，第一阶段聚焦 `/api/v1` 单一数据源、前端请求层、缓存一致性和消息同步边界。

## 关联规格
- SDD-P1-05：翻译异步化与数据库真源
- SDD-P1-02：真实未读计数
- SDD-P0-02：账号隔离与幂等
- QA-001：质量门禁
- NFR-PERF-001：前端响应与请求预算（本计划新增）

## Scope
- 统一 API client：认证、请求去重、短 TTL 缓存、mutation 失效、结构化错误。
- App 不再直接拼接认证 fetch；页面通过 feature 层调用 API。
- 会话/消息查询使用稳定 query key 和 cursor，不因无关状态刷新。
- 建立请求预算与性能日志，不改变现有公网 API 路径。
- 为翻译数据库批处理、SSE 增量同步、媒体代理、AI Job 预留明确边界；这些作为后续阶段，不伪装成已完成。

## Non-goals
- 本阶段不引入 Redis/PostgreSQL 集群。
- 不恢复 Legacy `/api/conversations`。
- 不改变 `/messages/{id}/translate` 兼容路径。
- 不在没有真实媒体 URL 时伪造媒体可用。

## RED → GREEN → REFACTOR
1. RED：增加 API client cache/dedupe、session isolation、mutation invalidation 和 request budget 测试。
2. GREEN：实现最小 client；替换设置页直连 fetch；接入现有 V1 请求。
3. REFACTOR：拆出 `web/src/features/*` hooks，保持页面行为和 API 契约不变。
4. Gate：`node --test web/tests/*.test.js`、`npm run build`、`pytest -q`、`bridge npm test/lint`、`git diff --check`。
5. Deploy：同步 FastAPI static assets，重启 systemd，验证 health、bundle、登录态 API 和日志。

## Acceptance
- 所有生产前端 API 请求通过统一 client；禁止业务组件直接调用裸 `fetch`。
- 同一 GET 在并发窗口只产生一次网络请求。
- session 切换清空旧缓存，401 不会读取旧用户数据。
- mutation 后只失效相关查询，不全量重拉所有 workspace 数据。
- 关键请求带 request timing（不包含 token/key/cookie/content）。
- 未完成的翻译数据库批处理、SSE、媒体代理、AI Job 保持在明确 backlog 中。
