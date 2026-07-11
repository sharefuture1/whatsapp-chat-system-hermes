# WA2 启动自动恢复连接实施计划

**对应规格**：FR-CON-012、API Bridge V2 `GET /accounts`

## Objective

Bridge 重启导致内存 AccountManager 为空时，FastAPI 依据业务数据库恢复 enabled、非 logged_out 账号的 Bridge 注册和连接；启动失败不阻塞 API，并以低频后台轮次持续幂等对账。

## Files

- Modify: `bridge/src/account-manager.js`, `bridge/src/server.js`
- Modify: `src/whatsapp_chat_system/bridge/client.py`, `src/whatsapp_chat_system/web_api.py`
- Create: `src/whatsapp_chat_system/accounts/reconciler.py`
- Test: `bridge/tests/account-manager.test.js`, `bridge/tests/server.test.js`
- Test: `tests/test_account_reconciler.py`, `tests/test_accounts_api.py`

## RED

1. Bridge manager/status list 与认证 `GET /accounts` 测试先失败。
2. Python reconciler 测试覆盖：缺失注册后连接、online 不重复连接、logged_out/disabled 跳过、单账号失败隔离。
3. FastAPI lifespan 测试覆盖启动立即执行、后台继续、shutdown 取消；Bridge 不可用不阻塞 API。
4. logout 必须持久化 `enabled=false`，防止下一轮自动重连。

## GREEN

最小实现安全状态列表、Bridge client list、独立 reconciler，以及 FastAPI lifespan 单后台 task；默认 45 秒轮询。

## Verification

- focused Python/Bridge tests
- Python full suite
- Bridge full suite + lint
- `git diff --check`

不提交代码，不修改 CORS/凭据，不实现联系人或历史同步。
