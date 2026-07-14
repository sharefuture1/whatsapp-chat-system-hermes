# SDD-P1-05 翻译数据库真源 — Phase 1 最小落地计划

## Objective
把当前“同步单条翻译 + JSON 文件缓存”推进到“数据库真源 + 异步批任务入口”的第一阶段，优先满足 SDD-P1-05 的核心边界，而不在本轮伪装成已完成 SSE/WebSocket。

## 关联规格
- SDD-P1-05：翻译异步化
- DATA-005 / DATA-006 / DATA-007
- QA-001

## 当前事实
- `POST /api/v1/messages/{message_id}/translate` 仍同步调用 Provider
- 译文写入 `translations__{user_id}.json`
- 前端 `ChatPane.jsx` 仍会逐条触发翻译请求
- `messages` 表无数据库译文字段/无翻译任务表

## Phase 1 Scope
1. 新增数据库真源表：`message_translations`
2. 新增最小批任务表：`translation_batches`
3. 消息列表 API 返回数据库译文状态
4. 新增会话级异步批量翻译入口：`POST /api/v1/conversations/{conversation_id}/translations`
5. 旧消息级翻译入口改为“创建任务 / 走数据库真源”，不再直接调 Provider
6. 先在 Standalone 进程内跑 `TranslationDispatcher`；暂不做独立 worker unit

## Non-goals
- 本轮不实现 SSE/WebSocket
- 本轮不删除 localStorage/cache-only 加速层
- 本轮不实现完整管理员预算/大规模调度面板
- 本轮不做跨实例分布式 claim

## RED → GREEN → REFACTOR
1. RED：新增模型/迁移/仓储/API focused tests
2. GREEN：最小实现数据库真源 + batch enqueue + worker
3. REFACTOR：前端逐步从单条 translateOne 迁移为会话级批触发
4. Gate：`pytest -q`、`npm run build`、`git diff --check`、`/api/health`

## Acceptance（Phase 1）
- 缺失译文时不再在 API 请求线程内直接调用 Provider
- 译文和失败状态进入数据库，不再写 JSON 文件作为主真源
- 同一消息内容不重复创建 completed 翻译记录
- 消息读取优先返回数据库译文
- 缺失译文时创建 batch 并返回 202/queued
- SSE/WebSocket 明确保留在后续阶段，不误标完成
