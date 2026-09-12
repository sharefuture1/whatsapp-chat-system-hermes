# Standalone 自动翻译单入口与 Worker 重试规格

> 状态：**Approved / Mandatory**
> 日期：2026-09-12
> 需求：`FR-AI-015`、`FR-AI-016`、`PERF-004`、`PERF-006`

## 1. 问题

当前 Standalone 已在 `message.upsert` 服务端自动创建 `TranslationBatch`，但 `ChatPane` 仍会扫描未翻译消息并自动 POST 批次；同时服务端入站创建没有统一检查管理员自动翻译开关和 Provider 可用性。这样页面打开与否会改变后台任务数量，且关闭开关后仍可能产生 AI 调用。

`TranslationDispatcher` 当前先 SELECT 再把 ORM 行改为 `running`，多 Worker 同时选择时缺少原子 CAS；异常把批次永久标为 `failed`，模型已有的 `retry_after` 没有形成自动重试状态机，旧 Worker 也缺少代次校验。

## 2. FR-AI-015 自动翻译单入口

1. Standalone 自动翻译任务只允许由已鉴权 WhatsApp `message.upsert` 入站链路创建。
2. Web 页面只读取数据库译文；不得通过自动 effect/轮询为 Standalone 未译消息创建批次。`POST /api/v1/conversations/{id}/translations` 仍可用于明确的手动翻译/历史补译。
3. 服务端入站必须解析同一份有效策略：
   - `plugins.auto_translate` 为真；
   - `message_ops.auto_translate` 为真；
   - effective AI API key 已配置；
   - 当前目标语言为已支持的 `zh-CN`；
   - `translation_context_window` 钳制到 `[1, 20]`，默认 10。
4. 设置 API 展示的 `ready/blocked_reason` 必须使用同一策略解析器，禁止 UI 与真正任务创建条件漂移。
5. 开关关闭或 AI 未配置时只跳过新自动任务，不删除历史译文、现有消息或 WhatsApp session。

### 验收

- 插件关 / 设置关 / AI 未配置三种情况下，真实 `message.upsert` 均不创建 `TranslationBatch`。
- 三项均满足时创建一次批次，并使用策略窗口；重复同一事件仍由既有事件幂等保证。
- Web 静态/单元回归证明 Standalone 自动路径不再 POST 翻译批次；Legacy 逐条自动翻译行为不回归。

## 3. FR-AI-016 Worker 原子领取与有界重试

1. 批次领取必须使用带 `id + status + attempt_count` 守卫的条件 `UPDATE`。SQLite/PostgreSQL 都不得依赖会被 SQLite 忽略的 `SELECT FOR UPDATE`。
2. 成功领取后 `attempt_count += 1`，该值作为本轮 `claim_attempt`。写回翻译结果、失败状态前必须确认数据库仍是 `running + claim_attempt`；旧代次结果直接丢弃。
3. 可选批次：
   - `pending/claimed` 且 `retry_after IS NULL OR retry_after <= now`；
   - 超过 `stale_running_seconds` 的 `running`；
   - `attempt_count < max_attempts`。
4. 可重试失败：
   - 若仍有预算，回到 `pending`，保留结构化错误并设置指数退避 `retry_after`；
   - 达到 `max_attempts` 进入 `dead`，清空 `retry_after` 并写 `completed_at`；
   - 部分消息失败同样按此批次重试，已完成消息下一轮不得重复调用 AI。
5. AI/外部调用继续严格遵守 PERF-006：短事务领取/快照 → 无 Session 调 AI → 新短事务按代次写回。

### 验收

- 两个 session 使用同一旧状态/attempt CAS，仅一个领取成功。
- 模拟批次被第二 Worker 重领后，第一 Worker 的迟到 `_finalize` 不写 MessageTranslation、不覆盖批次。
- 第一次失败可自动重试并第二次成功；连续失败达到上限进入 dead。
- 未来 `retry_after` 不会被提前领取。
- 完整 Python/Web/Bridge 门禁与 Browser/Tauri 构建通过。

## 4. 非目标

- 本轮不新增数据库列/迁移；利用现有 `attempt_count/retry_after/updated_at`。
- 本轮不扩展目标语言；聊天翻译仍仅 `zh-CN`。
- 本轮不启用任何生产账号自动回复或自动翻译开关，不清理生产历史数据。
