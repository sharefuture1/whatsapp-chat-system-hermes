# P0-01 规格审查修复计划（FR-AI-003/005/006/007）

## Objective

修复账号模型继承、AI 调用安全审计、设置 API、Provider 失败结构化传播和 SDD 状态误标，保持 Legacy 内部 fallback 兼容且不部署生产。

## Files

- Modify: `src/whatsapp_chat_system/config.py`
- Modify: `src/whatsapp_chat_system/ai/service.py`
- Modify: `src/whatsapp_chat_system/rewriter.py`
- Modify: `src/whatsapp_chat_system/web_api.py`
- Test: `tests/test_model_resolution.py`
- Test: `tests/test_rewriter_ai_service.py`
- Test: `tests/test_web_api.py`
- Test: `tests/test_translation.py`
- Docs: `docs/sdd/05-optimization-backlog.md`
- Docs: `docs/CHANGELOG_AGENT.md`
- Docs: `docs/PROJECT_MEMORY.md`
- Docs: `docs/TODO_AGENT.md`

## Acceptance

- 新建或缺字段迁移后的 `reply.ai_model` 为空，真实 `AppConfig` + `Rewriter` 使用环境全局模型；优先级为 contact > account > global。
- `AIService` 对成功和 `AIProviderError` 失败记录安全审计字段，不记录 key 或完整消息；`Rewriter` 默认构造时注入现有 logger。
- `GET /api/v1/ai/settings` 返回安全配置；Legacy `GET /api/settings` 返回 effective model/source，均不泄露 key。
- AI Provider fallback 在 `RewriteResult.error` 携带 code/retryable/request_id；reply preview 和 translate API 返回 `success=false` 与结构化 error，并可携带 fallback 文本。
- 非 Provider 的验证失败继续保持原 fallback 行为。
- 未部署时 SDD-P0-01 状态为 `Implemented`，项目文档不声称 Verified。

## TDD

1. RED：先新增上述集成、审计、rewriter 和 API 测试，运行目标 pytest 并确认失败。
2. GREEN：最小修改配置、服务、rewriter 和 API，使目标测试通过。
3. REFACTOR：清理重复错误序列化和模型解析，保持目标测试通过。
4. Gate：全量 `pytest -q`、`python -m py_compile`、前端 `npm run build`、`node --test tests/chatSync.test.js`、`git diff --check`。
5. 更新 SDD 与项目文档，提交单一 commit；不部署、不使用真实 key。
