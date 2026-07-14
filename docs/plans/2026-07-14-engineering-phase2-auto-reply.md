# 工程化重构 Phase 2：24x7 AI 自动回复

## Objective
在不依赖浏览器页面的前提下，让 AI 自动回复通过持久化 Job、AI Provider、Outbox 和 Bridge 形成可恢复闭环。

## 关联规格
- SDD-P0-09：24x7 AI 自动回复可靠性
- SDD-P0-05：Outbox 可靠发送
- SDD-P0-03：Bridge V2
- FR-AI-001~007、FR-MSG-004~006、QA-001

## 当前事实
- Standalone 已有 OutboxDispatcher 和 `analysis_jobs` Repository，但入站 `message.upsert` 目前只入库，不创建自动回复 Job。
- Standalone lifespan 已运行账号 reconciler 和 Outbox worker，但没有自动回复 Worker。
- 因此当前不能声称 24x7 自动回复已完成；必须先实现并测试。

## 实施顺序
1. RED：入站消息触发条件、幂等 key、人工回复竞态、暂停/限速、Worker recovery 测试。
2. GREEN：新增 AutoReply service，事务内创建 `analysis_jobs`；新增 worker claim/lease/AI 调用/Outbox 入队。
3. API：管理员设置自动回复策略和 `/api/v1/automation/health`；普通用户只读。
4. 状态：增加 heartbeat、失败原因、retry_at、dead 计数和熔断。
5. 部署：systemd API Worker 同进程初版，后续可拆独立 unit；重启恢复验证。
6. 真实验证：测试账号收消息、AI 生成、Outbox queued、Bridge 真实发送、receipt completed；持续观测 24 小时。

## 关键约束
- webhook 只做短事务入库/创建 Job，不同步调用 Provider。
- 任何 Job/Outbox 都必须 account scoped、幂等、可重试、可取消。
- 人工发送后，自动回复 Job 在执行前必须再次检查并取消。
- 不记录 API key、token、消息全文或用户密码到日志。
- AI 失败不能自动发送原文或伪造回复。

## Acceptance
- 相同入站 webhook 重放不会创建第二个 Job。
- API/Bridge 重启后 pending、claimed、retry Job 可恢复。
- AI timeout/429/5xx 按退避重试；永久错误进入 dead。
- 账号 offline 时不丢 Job，恢复后继续发送。
- admin pause 后不创建新 Job；普通用户无法修改策略。
- automation health 可显示 heartbeat、队列和熔断状态。
- 真实测试账号持续 24 小时运行，无永久 pending 增长、无重复自动回复。
