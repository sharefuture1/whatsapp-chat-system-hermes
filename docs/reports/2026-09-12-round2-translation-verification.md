# 第二轮翻译单入口与 Worker 重试：代码验收记录

状态：**Implemented / Code Verified**；**Production Verified 未完成**。

基线：`codex/p0-hardening-tauri2` 的 `474dc0ba86b8351e10515ee5b9849cc349a1bb75`。
实现提交：`0fd68c63daa7546b358b4fe794a2abd3d435fe93`（PR #8）。
规格：`FR-AI-015`、`FR-AI-016`、`PERF-004`、`PERF-006`。

## 完成内容

1. Standalone 自动翻译改为服务端入站单入口；浏览器不再自动创建翻译批次，显式手动/历史补译接口保留。
2. `translation_policy` 统一插件开关、消息自动翻译开关、有效 AI Key、目标语言和窗口配置；设置 API 与 capabilities 复用同一解析器。
3. TranslationDispatcher 使用条件 UPDATE / CAS 原子领取，`attempt_count` 作为领取代次；迟到 Worker 写回会被拒绝。
4. 可重试失败进入 `pending + retry_after` 的指数退避；达到 `max_attempts` 转 `dead`。已完成消息在下一轮不会重复调用 AI。
5. API 增加翻译错误、重试时间、批次 attempt/retry 状态，前端被动呈现服务端真实状态。

## 锁定 CI 证据

GitHub Actions run：`34681537160`，job：`103520944938`。

- Python 3.11.16 / uv 0.9.25 / Ruff 0.15.21 / Node 20.20.2。
- `uv sync --locked`、`npm ci`。
- Python：**393 passed / 7 skipped / 1 warning**。
- Web：**141 passed / 0 failed**。
- Bridge：**89 passed / 0 failed**，syntax check 通过。
- Browser production build：通过，主包 `index-Dc6R1fCS.js`。
- Tauri frontend build：通过，主包 `index-TJ5u0dbq.js`；Tauri shell 校验通过。
- Ruff check / format check / `git diff --check`：通过。

7 个 skipped 是需要显式外部 PostgreSQL 测试数据库的专项，未声称 PostgreSQL 实库验收。Starlette TestClient 有 1 个 httpx 迁移 deprecation warning。

## 发布边界

- 本轮没有数据库迁移，使用既有 `attempt_count` / `retry_after` / `updated_at`。
- 没有启用生产自动翻译或自动回复，没有修改密钥、WhatsApp session、客户消息。
- gcptw 没有在本轮部署；因此不能标记 Production Verified。
- npm 安装审计仍提示 Web 6 项（2 moderate / 4 high）及 Bridge 1 项 high；需后续根据 advisory 和运行时可达性逐项处理，不能直接 `--force` 升级。

## 下一优先级

1. 消息封装/编辑/未知类型解析，避免合法消息静默丢弃。
2. 会话真正游标分页和历史同步覆盖范围。
3. 自动回复生效配置统一（model/prompt/style）与 Outbox lease/结果不确定处理。
4. 依赖安全 advisory 分析和安全升级。
