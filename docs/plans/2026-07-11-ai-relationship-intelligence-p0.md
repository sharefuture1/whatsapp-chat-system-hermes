# AI 关系智能 P0 实施计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 建立单联系人会话总结、可解释人物画像、人工编辑保护和拟人回复上下文的完整后端与前端闭环。

**Architecture:** 在现有独立业务数据库上增加 Evidence → Claim → Snapshot 数据层；所有分析通过可靠 Worker 异步执行，FastAPI 提供查询、人工审核和任务触发 API，React 联系人详情展示画像、记忆、总结和证据。第一阶段不做全量自动扫描和多平台 Adapter，只预留统一接口。

**Tech Stack:** FastAPI、SQLAlchemy/Alembic、PostgreSQL-compatible schema、现有 AI Provider、Worker/Outbox、React/Vite、Node test、pytest。

---

## Task 1：冻结 P0 数据契约

**Files:**
- Modify: `docs/sdd/03-data-model.md`
- Modify: `docs/sdd/04-api-and-events.md`
- Test: `tests/test_sdd_profile_contract.py`

定义 `conversation_segments`、`conversation_summaries`、`profile_claims`、`profile_claim_evidence`、`contact_profile_snapshots`、`memory_items`、`analysis_jobs` 的列、约束、索引、状态机和 account/contact scope。

验收：测试校验所有表、人工锁定、证据外键、幂等键和分析版本均写入规格。

## Task 2：新增 Alembic 模型与迁移

**Files:**
- Modify/Create: `src/whatsapp_chat_system/db/models/*.py`
- Create: `alembic/versions/000x_ai_relationship_intelligence.py`
- Test: `tests/test_ai_profile_models.py`

先写失败测试，覆盖：

- 相同 segment + analyzer_version 不能重复；
- Claim 必须属于同一账号联系人；
- manual_lock 和 accepted 状态持久化；
- Snapshot 可由 Claim 版本重建；
- job idempotency key 唯一。

运行升级→降级→升级验证。

## Task 3：实现 Profile Repository

**Files:**
- Create: `src/whatsapp_chat_system/ai/profile_repository.py`
- Test: `tests/test_profile_repository.py`

实现：

- upsert proposed Claim；
- attach evidence；
- accept/reject/lock/edit；
- 模型更新不得覆盖 manual_lock；
- 冲突生成新 proposed Claim；
- 根据 accepted/manual Claim 重建 Snapshot。

## Task 4：实现会话切片和增量总结

**Files:**
- Create: `src/whatsapp_chat_system/ai/segmenter.py`
- Create: `src/whatsapp_chat_system/ai/summary_service.py`
- Test: `tests/test_conversation_summary.py`

覆盖空闲阈值、消息上限、人工切片、增量游标、重复执行幂等、消息编辑/删除后 stale。

AI 输出必须使用结构化 Schema；解析失败进入 retryable job failure，不保存伪总结。

## Task 5：实现画像提取与聚合 Worker

**Files:**
- Create: `src/whatsapp_chat_system/ai/profile_worker.py`
- Modify: Worker 入口文件
- Test: `tests/test_profile_worker.py`

流程：summary.completed → 提取 Claims → 安全过滤 → 证据绑定 → 冲突检测 → Snapshot 重建 → 发布事件。

禁止敏感属性推断；低置信结论保持 proposed。

## Task 6：联系人画像 API

**Files:**
- Modify: `src/whatsapp_chat_system/web_api.py` 或拆分 router
- Test: `tests/test_profile_api.py`

新增：

```text
GET  /api/v1/contacts/{id}/profile
PATCH /api/v1/contacts/{id}/profile/claims/{claim_id}
POST /api/v1/contacts/{id}/profile/refresh
GET  /api/v1/contacts/{id}/summaries
GET  /api/v1/contacts/{id}/memories
DELETE /api/v1/contacts/{id}/memories/{memory_id}
GET  /api/v1/analysis-jobs/{job_id}
```

所有接口校验 account scope、RBAC 和审计；人工修改后即时重建 Snapshot。

## Task 7：回复上下文编排

**Files:**
- Create: `src/whatsapp_chat_system/ai/context_orchestrator.py`
- Modify: AI reply preview service
- Test: `tests/test_ai_context_orchestrator.py`

按当前消息、open loops、manual/accepted Claim、相关记忆、rolling summary、沟通偏好装配有 Token 预算的上下文。

测试必须证明 rejected/expired/低置信/跨账号内容不会进入 Prompt，联系人消息中的指令不会成为 system instruction。

## Task 8：联系人详情五 Tab UI

**Files:**
- Create/Modify: `web/src/components/ContactIntelligencePanel.jsx`
- Modify: 联系人详情/抽屉组件
- Modify: `web/src/styles.css`
- Modify: `web/src/i18n.js`
- Test: `web/tests/contactIntelligence.test.js`

实现概览、画像、记忆、总结、AI 策略。每条 Claim 显示来源、置信度、状态，支持确认、拒绝、编辑、锁定和证据抽屉。

移动端使用全屏分级页面；聊天页只显示画像状态和轻量入口。

## Task 9：插件配置与 readiness

**Files:**
- Modify: Plugin catalog/service
- Create: `conversation_summary`、`contact_profile_ai` 插件定义
- Modify: Plugin Center UI
- Test: Python + Web plugin tests

插件详情显示真实 hooks、Worker readiness、频率、阈值、字段白名单、敏感策略、预算和最近任务。Worker 不可用时后端拒绝启用。

## Task 10：真实验收与文档

执行：

```text
pytest -q
node --test web/tests/*.test.js
npm --prefix web run build
npm --prefix bridge test
npm --prefix bridge run lint
git diff --check
```

浏览器验收：390×844 与 1440×900；验证单联系人刷新、任务状态、证据查看、人工锁定、回复解释和资源哈希。

更新 SDD 状态、`CHANGELOG_AGENT.md`、`PROJECT_MEMORY.md`、`DECISIONS.md`、`TODO_AGENT.md`，再部署、提交和推送。

## P1 后续计划

P0 验证后再写独立计划实现：

- `bulk_profile_sync` 批量插件；
- dry-run、费用预估、预算、暂停/取消/重试；
- 自动日报/周报和待跟进中心；
- pgvector 相关记忆检索；
- Telegram Business/Bot Adapter。
