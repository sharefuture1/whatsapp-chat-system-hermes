# WhatsApp Chat System — SDD 总纲

> Software Design & Development Specification
>
> 状态：**Active / Mandatory**  
> 规格版本：`1.0.0`  
> 基线日期：`2026-07-10`

## 1. 权威性

`docs/sdd/` 是本项目需求、架构、接口、数据模型、开发流程和验收标准的**唯一权威规格源**。

以后所有开发必须遵循：

```text
需求变更
  → 更新 SDD
  → 评审影响范围
  → 编写失败测试
  → 最小实现
  → 运行质量门禁
  → 更新 SDD 状态及项目四文件
  → 部署和线上验证
```

严禁：

- 未更新规格就直接修改业务代码；
- 实现与 SDD 不一致后只改代码、不改文档；
- 用 `TODO_AGENT.md` 代替正式需求与验收标准；
- 把原型、占位按钮或仅保存配置描述成“功能完成”；
- 未跑测试、构建和真实接口验证就标记完成；
- 把密钥、token、密码、WhatsApp session 凭据写入 SDD 或 Git。

## 2. 文档索引

1. [`01-product-requirements.md`](./01-product-requirements.md)  
   产品范围、角色、核心场景、功能需求、非功能需求与完成定义。
2. [`02-system-architecture.md`](./02-system-architecture.md)  
   独立运行目标、系统边界、组件职责、关键流程、Hermes 解耦方案。
3. [`03-data-model.md`](./03-data-model.md)  
   多账号数据隔离、核心实体、约束、消息状态机、任务状态机。
4. [`04-api-and-events.md`](./04-api-and-events.md)  
   REST API、Bridge 内部 API、Webhook 事件、错误和幂等契约。
5. [`05-optimization-backlog.md`](./05-optimization-backlog.md)  
   所有待优化事项、优先级、依赖关系、验收标准与状态。
6. [`06-development-workflow.md`](./06-development-workflow.md)  
   强制 SDD/TDD 流程、任务模板、代码审查、测试、部署和文档门禁。
7. [`07-migration-and-rollout.md`](./07-migration-and-rollout.md)  
   从 Hermes 运行时迁移到独立系统的阶段、回滚与上线策略。
8. [`08-ai-relationship-and-multichannel.md`](./08-ai-relationship-and-multichannel.md)
   会话总结、长期记忆、人物画像、拟人回复、插件批处理及 Telegram/Meta 多平台账号目标架构。
9. [`09-performance-and-realtime.md`](./09-performance-and-realtime.md)
   性能审计结论、PERF 系列强制需求（刷新调度、轮询负载、连接复用、翻译数据库化、DB 健康、Worker 事务隔离、索引对齐、渲染稳定）与 RT 系列 SSE 实时同步契约。
10. [`10-frontend-vercel-deployment.md`](./10-frontend-vercel-deployment.md)
    前端 Vercel 托管拓扑与 VCL 系列需求：构建产物合同、`VITE_API_BASE_URL` 直连模式、CORS/鉴权、SSE 兼容、Preview 环境隔离、缓存版本验证与回滚。

补充实施计划：

- [`../plans/2026-07-10-standalone-wendingai-multi-account.md`](../plans/2026-07-10-standalone-wendingai-multi-account.md)
- [`../plans/2026-07-11-ai-relationship-intelligence-p0.md`](../plans/2026-07-11-ai-relationship-intelligence-p0.md)

## 3. 产品目标

构建一套可独立部署、稳定运行的多账号 WhatsApp 客服系统：

- 不依赖 Hermes CLI、profile、gateway 或 Hermes `state.db`；
- 直接接入问鼎 AI OpenAI-compatible API；
- 默认模型为 `gpt-5.3-codex-spark`；
- 支持多个 WhatsApp 账号在同一控制台扫码登录、隔离运行和统一管理；
- 支持可靠收发、AI 回复建议、翻译、联系人画像、插件、定时与群发；
- 具备幂等、队列、重试、审计、权限、监控和可回滚能力；
- 保持微信式、移动优先、真实可操作的交互体验。

## 4. 架构原则

1. **FastAPI 是业务真源**：业务状态必须进入独立数据库。
2. **Bridge 只处理 WhatsApp 协议**：不承载业务规则。
3. **AI Provider 独立**：所有模型调用经过统一适配层。
4. **账号强隔离**：所有联系人、会话、消息和任务必须有 `account_id`。
5. **可靠异步**：发送、群发、定时任务采用 Outbox/Worker。
6. **状态真实**：前端只能显示后端或 WhatsApp 已确认的状态。
7. **插件真接线**：无真实后端 hook/worker 的插件不得标记为可用。
8. **规格先行**：代码、测试和部署必须能追溯到 SDD 需求 ID。
9. **渐进迁移**：切换前保持旧系统可回滚，不直接删除旧数据。
10. **秘密不入库/不入 Git**：API key 和 WhatsApp 凭据由环境和受控存储管理。

## 5. 需求编号规则

- `FR-*`：功能需求
- `NFR-*`：非功能需求
- `SEC-*`：安全需求
- `DATA-*`：数据约束
- `API-*`：接口契约
- `UX-*`：交互需求
- `MIG-*`：迁移需求
- `QA-*`：质量门禁

代码提交、测试名称、变更记录应引用对应 ID，例如：

```text
feat(accounts): add QR login state machine [FR-ACC-002]
test(messages): prevent cross-account message leakage [DATA-004]
```

## 6. 规格状态规则

每个需求只能处于：

- `Draft`：待确认；不得进入生产实现；
- `Approved`：可开发；
- `In Progress`：已有对应任务和测试；
- `Implemented`：代码完成但未完成全量验收；
- `Verified`：测试、构建、运行和文档全部通过；
- `Deprecated`：被新规格替代，必须说明替代项。

只有 `Verified` 才能在 `TODO_AGENT.md` 标记完成。

## 7. 当前基线

当前生产仍是 Legacy 模式：

- FastAPI/React：`127.0.0.1:8792`；
- WhatsApp Bridge：`127.0.0.1:3000`；
- Hermes gateway 仍负责启动单账号 Bridge；
- 数据仍来自 Hermes profile 与 `state.db`；
- 独立化方案已批准，但尚未执行生产切换。

后台通知中的 `Uvicorn running on http://127.0.0.1:8792` 仅表示当前服务已启动，不代表独立化迁移完成，也不代表重复进程。
