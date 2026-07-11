# AI 关系智能与多平台账号架构

> 状态：P0 Approved；P1/P2 Draft。用户已批准 P0 数据/API 契约进入开发，但本文不表示生产功能已经实现；多平台 Adapter 与后续自动化范围仍待单独批准。

## 1. 产品目标

系统从“多账号聊天聚合器”升级为“关系智能工作台”：

- 自动形成可解释、可编辑、可追溯的人物画像；
- 定期总结会话，识别人物特点、偏好、关系变化、承诺和待办；
- AI 回复结合当前语境、历史摘要、可靠记忆和用户自身口吻，更自然但不伪造事实；
- 管理员可通过插件批量为全部联系人生成或刷新画像；
- WhatsApp、Telegram、Facebook Page Messenger、Instagram、WhatsApp Cloud API 使用统一账号与消息模型；
- 平台适配层负责协议，业务、AI、画像和插件不依赖具体平台。

## 2. 模块划分

```text
React 工作台
 ├─ 统一收件箱
 ├─ 联系人画像中心
 ├─ 总结/记忆/证据时间线
 ├─ AI 回复解释与人工编辑
 ├─ 批处理任务中心
 └─ 多平台账号中心
          │ REST + SSE/WebSocket
FastAPI Control Plane
 ├─ Identity & Channel Account Service
 ├─ Conversation Service
 ├─ Profile/Memory Service
 ├─ Context Orchestrator
 ├─ Plugin & Policy Service
 └─ Job API / Audit
          │
PostgreSQL + pgvector + Redis/Queue
          │
Worker Pool
 ├─ Conversation Segmenter
 ├─ Summary Worker
 ├─ Memory Extractor
 ├─ Profile Aggregator
 ├─ Bulk Profile Sync
 └─ Reply Planning/Evaluation
          │ normalized events / outbox
Platform Adapters
 ├─ WhatsApp Baileys Bridge（迁移期）
 ├─ WhatsApp Cloud API Adapter
 ├─ Telegram Bot/Business Adapter
 ├─ Telegram TDLib Adapter（高级可选）
 └─ Meta Messenger/Instagram Adapter
```

## 3. AI 关系智能

### 3.1 三层信息模型

禁止把人物画像保存成一段由模型反复覆盖的 Markdown。采用三层模型：

1. **Evidence**：消息、人工备注、会话总结等证据；
2. **Claim**：从证据得到的结构化事实或推断；
3. **Snapshot**：面向页面和 Prompt 的当前画像快照，可随时由 Claim 重建。

Claim 必须包含：

```text
contact_id
category                  # fact/preference/style/relationship/goal/caution
key/value_json
source_type               # explicit_fact/observed_pattern/model_inference/manual
confidence                 # 0..1
status                     # proposed/accepted/rejected/superseded/expired
sensitivity               # normal/private/restricted
valid_from/valid_until
analyzer_version
created_by                 # worker/operator
manual_lock                # 人工锁定后模型不得覆盖
```

每条 Claim 通过 `profile_claim_evidence` 关联具体消息或总结。模型推断必须在 UI 中标记“AI 推断”，不得包装为确定事实。

### 3.2 会话总结

按增量游标切分会话片段：

- 空闲时间超过阈值；
- 话题明显变化；
- 消息数量/Token 达到上限；
- 人工触发。

总结结构：

```json
{
  "topics": [],
  "decisions": [],
  "open_loops": [],
  "promises": [],
  "preferences_observed": [],
  "relationship_events": [],
  "sentiment": {},
  "mentioned_entities": []
}
```

支持 segment/daily/weekly/rolling 四级总结。旧总结不能直接被覆盖，使用版本和 superseded 关系。

### 3.3 长期记忆

只保存未来回复有价值的信息：

- 联系人明确表达的事实和偏好；
- 已确认的关系背景；
- 未完成承诺和待办；
- 沟通禁忌和回复偏好；
- 重要时间、产品需求或业务阶段。

每条记忆具有重要度、时效性、最后验证时间和来源。检索按 contact/account/tenant 强隔离，结合关键词、结构化过滤、时间衰减和向量相似度。

### 3.4 更拟人的回复链

```text
Intent/Context Detector
 → Memory Retriever
 → Reply Planner
 → Reply Writer
 → Factual/Policy Guard
 → Candidate + Explanation
```

上下文预算按优先级装配：

1. 当前消息和最近对话；
2. 当前未完成事项；
3. 人工确认/锁定的画像事实；
4. 与当前话题相关的高置信记忆；
5. 最近滚动总结；
6. 联系人沟通偏好；
7. 当前账号或操作员的表达风格。

必须区分：

- **联系人画像**：对方是谁、偏好什么；
- **操作员风格画像**：我们应该如何表达。

不得简单模仿联系人的口吻。回复结果应返回 `used_memories`、`used_claims`、模型和风险提示，前端默认收纳在“为什么这样回复”中。

### 3.5 防臆测和隐私

- 默认禁止推断种族、宗教、疾病、政治倾向、性取向等敏感属性；
- 心理和人格仅允许描述可观察沟通倾向，不作医学诊断；
- 无足够证据时保存为 proposed，不能进入自动回复强约束；
- 人工修改优先，模型只能提出冲突建议；
- 支持联系人级关闭分析、删除记忆、重新计算和数据导出；
- 引用的聊天文本必须按角色标记，防止联系人消息中的指令成为系统 Prompt。

## 4. 插件设计

新增真实插件：

### `conversation_summary`

- hooks：`message.ingested`、`summary.worker`；
- 配置：启用范围、空闲切片分钟数、最小消息数、日报/周报时间、保留期；
- 页面：插件详情可看最近任务、失败、费用和总结数量。

### `contact_profile_ai`

- hooks：`summary.completed`、`profile.worker`、`reply.context`；
- 配置：字段白名单、最低置信度、自动接受阈值、敏感字段策略、更新频率；
- 页面：展示 Claim 类型、证据要求和 Prompt 上下文开关。

### `bulk_profile_sync`

- hooks：`profile.bulk_job`；
- 配置：平台/账号/标签范围、并发、批大小、每日 Token/费用上限、只处理 stale/empty、dry-run；
- 页面：预估联系人数量和费用，开始/暂停/取消/失败重试、逐项结果和审计。

插件状态必须由 Worker 能力决定。Worker 未运行或队列不可用时返回 `available=false`，不能只显示可点击开关。

## 5. 前端信息架构

### 5.1 聊天页

保持克制，仅增加：

- 联系人标题旁画像状态点：空/处理中/已更新/需确认；
- 当前联系人抽屉新增“画像”Tab；
- AI 候选回复可展开“使用了哪些记忆/为什么这样回复”；
- 当前聊天“立即总结/刷新画像”放进更多菜单，不增加常驻按钮。

### 5.2 联系人详情

五个 Tab：

1. **概览**：关系阶段、语言、标签、关键特点、最近变化；
2. **画像**：结构化字段，可编辑、确认、锁定、拒绝；
3. **记忆**：事实/偏好/待办/禁忌，支持搜索和删除；
4. **总结**：会话时间线、日报、周报、open loops；
5. **AI 策略**：模型、回复风格、自动回复、可用画像字段。

每个 AI 字段都可展开证据抽屉，显示来源消息、时间、置信度和分析版本。

### 5.3 关系智能中心

“发现”页增加关系智能入口：

- 总联系人、已画像、待更新、待人工确认、失败；
- 人物标签和关系阶段筛选；
- 批量生成/刷新画像；
- 任务队列、费用、模型延迟和错误；
- 最近人物变化、待跟进和承诺汇总。

### 5.4 插件中心

插件详情不是只有开关，而包含：

- 功能说明和真实 hooks；
- global/account 两级配置；
- 运行状态和 Worker readiness；
- 调度与预算；
- 最近任务与日志；
- Dry run；
- 数据权限和保留策略。

## 6. 多平台账号接入

### 6.1 统一账号抽象

```text
channel_accounts
 id, tenant_id, platform, connection_type, external_account_id,
 display_name, status, capabilities_json, credential_ref,
 token_expires_at, last_sync_cursor, connected_at
```

`connection_type` 示例：

```text
whatsapp_baileys
whatsapp_cloud
telegram_bot
telegram_business
telegram_tdlib_user
facebook_page
instagram_page_linked
instagram_direct
```

平台 Adapter 统一实现：

```text
connect / disconnect / refresh_credentials
send_message / send_media / mark_read
normalize_webhook / replay_event
capabilities / policy_check
```

业务层只消费标准事件，不出现平台专属字段判断。平台原始数据保留在 adapter metadata 中。

### 6.2 Telegram

推荐分三级：

1. **Telegram Business Connected Bots（首选客服方案）**
   - 业务账号在 Telegram 客户端授权连接 Business Bot；
   - 后端保存 Bot Token，一个 Bot 可通过 `business_connection_id` 服务多个业务账号；
   - 适合真实业务账号的客户私聊，不要求平台收集手机号、验证码和 2FA；
   - 主要从授权后接收事件，不适合导入完整历史。

2. **Bot API**
   - BotFather 创建，每个 Bot 一个 Token；
   - 适合 AI Bot、通知、群机器人；
   - 不能读取普通用户账号收件箱和完整历史。

3. **TDLib 用户账号（高级可选）**
   - 仅在需要完整用户账号、群组、频道和历史同步时使用；
   - 支持手机号验证码、二维码和 2FA 登录；
   - 每账号独立 TDLib 实例、数据库、下载目录和发送队列；
   - 定位必须是用户明确授权的第三方 Telegram 客户端，禁止批量 userbot、陌生人营销或规避风控。

官方资料：

- Bot API：https://core.telegram.org/bots/api
- Business Connected Bots：https://core.telegram.org/api/bots/connected-business-bots
- TDLib：https://core.telegram.org/tdlib
- 登录：https://core.telegram.org/api/auth
- QR 登录：https://core.telegram.org/api/qr-login
- API 条款：https://core.telegram.org/api/terms

### 6.3 Facebook / Instagram / WhatsApp Cloud

只采用 Meta 官方 Business Messaging：

- Facebook：Messenger Platform，主体是 Facebook Page；
- Instagram：Business/Creator 专业账号，支持 Page-linked 或 Instagram Login；
- WhatsApp：Cloud API，自有企业先用 System User，多租户 SaaS 使用 Embedded Signup；
- 个人 Facebook Profile Messenger 没有官方第三方收件箱 API，明确不支持 Cookie、浏览器自动化或私有接口逆向。

登录与授权：

- Facebook Page / Page-linked Instagram：Facebook Login for Business；
- Instagram 独立专业账号：Business Login for Instagram；
- WhatsApp SaaS：Embedded Signup；
- Token 服务端加密保存，前端只显示授权状态和到期时间。

所有 Meta 出站消息进入 Policy Gateway：

- Messenger/Instagram 24 小时窗口；
- WhatsApp Customer Service Window；
- 窗口外模板、Message Tag、用户 opt-in；
- 发送依据、操作人、模板和策略结果写审计。

官方资料：

- Messenger Platform：https://developers.facebook.com/documentation/business-messaging/messenger-platform/
- Instagram Messaging：https://developers.facebook.com/documentation/business-messaging/instagram-messaging/overview/
- WhatsApp Cloud API：https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started/
- WhatsApp Embedded Signup：https://developers.facebook.com/docs/whatsapp/embedded-signup/implementation

## 7. 分期建议

### P0：画像基础和页面闭环（Approved）

- 新表：segment/summary/profile_claim/evidence/snapshot/memory/job；
- 单联系人手动总结和刷新画像；
- 联系人详情五 Tab；
- 人工编辑、确认、锁定、拒绝、证据查看；
- 回复预览接入人工确认的画像与最近总结；
- Plugin 配置 Schema 和真实 Worker readiness。

### P1：自动化和批处理（Draft）

- 增量总结与画像 Worker；
- 全部联系人批量同步插件；
- Dry run、费用预算、暂停/取消/重试；
- 周报、待跟进和承诺中心；
- pgvector 相关记忆检索；
- Telegram Business/Bot Adapter。

### P2：平台扩展和高级智能（Draft）

- Meta Page/Instagram/WhatsApp Cloud Adapters 与 Policy Gateway；
- Telegram TDLib 高级 Adapter；
- 跨渠道身份由人工或验证流程合并，禁止模型自动合并；
- 操作员风格学习、离线回复质量评测、A/B Prompt 版本；
- PostgreSQL/Redis 正式生产化和完整可观测性。

## 8. 核心验收

- 任何画像结论可以追溯到证据，人工锁定内容不会被 Worker 覆盖；
- 重复执行相同消息区间不产生重复总结、Claim 或任务；
- 新消息只从游标后增量处理；编辑/删除消息触发受影响结果 stale/recompute；
- 批量任务可暂停、取消、重试并遵守账号/租户、预算和并发限制；
- AI 回复不得使用 rejected、expired、低置信或越权记忆；
- 每个页面功能都有真实 API、数据库和 Worker 路径；
- 每个平台发送都锁定原 channel account，并执行平台政策检查；
- Token、验证码、2FA、session 和消息内容不出现在日志、前端响应或 Git 中。
