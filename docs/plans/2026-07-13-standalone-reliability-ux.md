# Standalone 可靠性与聊天体验修复计划

日期：2026-07-13
分支：`fix/standalone-reliability-ux-20260713`

## 目标

在不提前执行生产切流、不删除 Legacy 回滚链路的前提下，修复代码审查中可以独立验证的高优先级缺陷，并为后续 Standalone V1 单源迁移建立质量门禁。

## 本轮范围

### QA-REL-001：AI 动态重试配置

- HTTP 429/5xx 与 timeout 统一使用运行时 `effective_retries`。
- 增加运行时覆盖值回归测试。

### API-MSG-014：Standalone 历史消息分页

- `/api/v1/conversations/{conversation_id}/messages` 支持稳定 cursor：
  - `before_occurred_at`
  - `before_id`
- 返回真实 `total_messages`、`has_more` 和 `next_cursor`。
- 同时间消息使用 ID 作为稳定次序，避免重复或遗漏。
- 时间写入统一使用 UTC aware datetime。

### UX-APP-015：迁移期前端降级

- Standalone 明确返回 `410 legacy_api_disabled` 时，仅对已知只读 Legacy 端点提供安全空数据。
- 不吞掉其他 4xx/5xx。
- 结构化错误对象提取真实 message/code，避免 UI 显示 `[object Object]`。

### SEC-004：Standalone Web 安全边界

- CORS 从通配符调整为显式域名列表。
- 支持 `CHAT_SYSTEM_ALLOWED_ORIGINS` 配置附加正式域名。
- 登录增加按客户端 IP 的窗口限流，并持久化失败尝试。
- Bridge 未配置实现补齐 `send` 的 fail-closed 行为。

### QA-001：远程质量门禁

新增 GitHub Actions：

- Python：Ruff + Pytest；
- Web：Node tests + Vite production build；
- Bridge：Node tests + syntax checks；
- Git diff whitespace 检查。

## 明确不在本轮宣称完成

- Outbox Worker 与发送幂等；
- 前端完整 V1 单源；
- 联系人备注/AI 覆盖从旧 `user_id` 键迁移至 `account_id + contact_id`；
- 双账号真实扫码、收发、断线隔离；
- 生产 systemd 安装、切流与回滚演练；
- Cookie Session、CSRF 与 Redis/PostgreSQL Session 存储。

上述事项仍按 SDD P0 主线继续执行，未完成真实环境验收前不得标记 `Verified`。
