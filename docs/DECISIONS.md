# DECISIONS.md — 架构决策记录

## 2026-07-10: V2 账号会话必须从独立业务库按 account_id 展示

**决策**：账号中心中的 V2 账号状态与聊天首页必须使用同一独立业务数据库。聊天列表新增 `all|account_id` 作用域；独立会话详情使用 conversation UUID，不再用 JID 查询 Legacy `state.db`。

- 页面不能因迁移期保留 Legacy API 而隐藏已成功落入独立库的 V2 消息。
- 聚合视图中每条会话必须携带 `account_id` 和账号名；单账号筛选必须在服务端查询层生效。
- 账号切换必须清空旧会话选择，避免把 A 账号选中的联系人内容显示在 B 账号上下文。
- Legacy 消息链暂时保留作为回滚兼容，但不能再作为 V2 账号的显示真源。
- 当前实例仅有一个 V2 业务账号，因此不能将“两个账号同时在线和隔离”标记为完成。

---

## 2026-07-10: Legacy 网页直发成功必须同步写回页面消息源

**决策**：迁移期 `/api/reply` 仍通过 Legacy Bridge 发送时，只有底层明确返回成功和真实 WhatsApp message ID 后，FastAPI 才把 outbound assistant 消息写入 Hermes `state.db`。

- 页面消息源仍是 `state.db`，不能只依赖浏览器 optimistic bubble。
- 写回保存本地 message ID 与 `platform_message_id`；API 同时返回两者供前端稳定合并。
- 发送失败不得落库为成功消息，前端保留失败 bubble、错误文案和原地重试。
- 该方案只解决迁移期 Legacy 同步缺口；Bridge V2 正式发送仍按业务库 Outbox/事件回执规格实现。

---

## 2026-07-10: Bridge V2 使用持久化 spool，并在真实账号验收前保持影子模式

**决策**：Bridge V2 的事件投递采用每账号单 writer 的磁盘 FileSpool；任何账号状态、消息或回执先持久化，再发送至 FastAPI 内部事件接口。

- 每账号仅一个 `EventSink/FileSpool` owner，重启 replay 后注册账号必须复用同一 owner。
- 事件唯一边界为 `(account_id,event_id)`；相同 ID 的 canonical envelope 不一致必须显式冲突，不得静默覆盖。
- FastAPI 以单事务写入事件、联系人、会话和消息；状态与回执按 sequence/rank 单调。
- QR、session credential、底层路径和 token 不进入 webhook、状态 API 或用户响应。
- Legacy Bridge `3000` 在 V2 真实扫码、收发、session 恢复和双账号验收前保持运行；V2 使用 `3100` 影子验证，不提前切流。
- 无真实 WhatsApp 账号的 health/auth/create/status/stop 验证只能证明运行和安全门禁，不能将需求标记为 `Verified`。

详细实现：`docs/plans/2026-07-10-bridge-v2-account-center.md` Task 5/6。

---

## 2026-07-10: Bridge V2 未配置时 fail-closed，账号 UI 不伪造登录

**决策**：账号控制面可以先于独立 Node/Baileys Bridge V2 上线，但不得用假 QR、静态状态或数据库预写 `online` 冒充已登录。

- `WHATSAPP_BRIDGE_INTERNAL_TOKEN` 未配置时，Bridge 写操作返回结构化 `bridge_not_configured`。
- 创建账号只有在 Bridge 注册成功后才对用户视为成功；注册失败补偿删除业务记录。
- `connect` 只返回已受理，不提前改为在线；账号状态最终由后续 Bridge 事件更新。
- 新账号默认 `auto_reply_mode=off`，真实连接和事件链验收前不默认开启自动回复。
- 用户可见设置不再暴露 Hermes profile/path/CLI，Legacy 兼容仅保留在服务器迁移层。

详细计划：`docs/plans/2026-07-10-bridge-v2-account-center.md`。

---

## 2026-07-10: SDD 成为强制开发规格

**决策**：`docs/sdd/` 成为本项目需求、架构、数据模型、API、优化清单、开发流程和迁移策略的唯一权威规格源。

所有后续任务必须：

1. 先读取并确认相关 SDD；
2. 绑定需求 ID；
3. 复杂任务先写实施计划；
4. 使用 RED → GREEN → REFACTOR；
5. 完成规格符合性和代码质量审查；
6. 通过全量门禁和真实运行验证；
7. 更新 SDD 状态及项目四文件。

`TODO_AGENT.md` 只作为当前执行视图；旧 `docs/SDD.md` 和 `docs/ARCHITECTURE.md` 不再承载完整权威规格。紧急修复也必须在同一任务内补齐 SDD 和回归测试。

---

## 2026-07-10: 独立运行、问鼎 AI 与多 WhatsApp 账号架构

**现状证据**：

- 当前 FastAPI 从 Hermes profile 的 `config.yaml`、`state.db` 和 JSON sidecar 读取配置/消息。
- 当前发送路径先调用本机 `127.0.0.1:3000` Bridge，失败后回退 `hermes --profile ... send`。
- 当前 Bridge 由 Hermes gateway 拉起，进程内只有一个全局 Baileys `sock` 和一个内存消息队列。
- 当前数据表没有 `account_id`，`workspace_id` 实际只等于 `source=whatsapp`，不能隔离多个 WhatsApp 账号。

**决策**：采用“FastAPI 控制面 + 独立多账号 Baileys Bridge + 业务数据库 + Worker + React 管理台”。

- 运行时不依赖 Hermes CLI、Hermes profile、Hermes gateway 或 Hermes `state.db`。
- 问鼎 AI 使用 OpenAI-compatible API：`https://wendingai.future1.us/v1`。
- 全局默认模型固定为 `gpt-5.3-codex-spark`；优先级为联系人 override > 账号 AI profile > 全局默认。
- 每条联系人、会话、消息、任务必须带 `account_id`；联系人全局键是 `(account_id, remote_jid)`。
- Bridge 每账号独立 socket 和 session 目录，通过 webhook 幂等推送消息事件。
- 发消息使用数据库 Outbox；定时与群发由真实 Worker 执行。
- 旧 Hermes 数据仅通过只读 importer 一次性迁移，迁移后不参与运行。

**详细实施方案**：`docs/plans/2026-07-10-standalone-wendingai-multi-account.md`。

---

## 2026-07-09: StaticFiles `/assets` mount path bug

**问题**：Starlette StaticFiles mount 到 `/assets` 时，URL path `/assets/index.js` 会被 strip `/assets` 前缀，然后查找 `directory/index.js`。但文件实际在 `dist/assets/index.js`，导致 404。

**决策**：mount 时 `directory` 参数指向 `frontend_dist / 'assets'`，而非 `frontend_dist`。

```python
# 错误（会导致 404）
app.mount('/assets', StaticFiles(directory=frontend_dist), name='web-assets')

# 正确
app.mount('/assets', StaticFiles(directory=frontend_dist / 'assets', check_dir=True), name='web-assets')
```

**涉及文件**：`src/whatsapp_chat_system/web_api.py`

---

## 2026-07-09: SPA serving 方案

**决策**：FastAPI 直接挂载 `web/dist`，不使用 nginx 静态文件服务。

**优点**：
- 单一进程，无需额外 web server
- `--web-dist` CLI 参数显式控制
- catch-all路由 `/{full_path:path}` 处理 SPA 路由

**验证**：
```
/api/* → FastAPI handlers
/assets/* → StaticFiles (dist/assets/)
/ → dist/index.html (catch-all)
```

---

## 2026-07-09: 前端 CSS 类名规范

**决策**：统一使用 `.wx-*` 前缀，避免与第三方库冲突。

设计 token：
- `--wx-brand`: 主品牌绿 `#07C160`
- `--wx-bg`: 背景 `#EDEDED`
- `--wx-surface`: 面板 `#F5F5F5`
- `--wx-text`: 主文字 `#1A1A1A`
- `--wx-text-secondary`: 次文字 `#888`
- `--wx-text-muted`: 弱文字 `#999`
- `--wx-border`: 分割线 `#E5E5E5`

组件类：
- `.wx-shell` / `.wx-shell-content` / `.wx-shell-header`
- `.wx-tab-bar` / `.wx-tab-btn`
- `.wx-list-item` / `.wx-avatar` / `.wx-badge`
- `.wx-bubble` / `.wx-composer`
- `.wx-skeleton` / `.wx-spinner`
- `.wx-modal` / `.wx-primary-btn`

---

## 2026-07-09: i18n 管理策略

**决策**：4 语言（en/zh/th/lo）全部对齐，所有 key 在 4 个 block 的行号严格对应。

**工具**：sed 精确行号插入（不依赖 patch 的字符串匹配）

**验证**：`grep -n "^    key:" i18n.js` 对齐所有 4 个 block

---

## 2026-07-08: pinned 状态来源

**决策**：pinned 列表使用后端 `/api/conversations` 返回的 `item.pinned` 布尔字段，不在前端维护独立 state。

前端仅维护 `Set<user_id>` 用于快速查找，pinned 分组直接从 conversations 列表 filter。

---

## 2026-07-10: 增量消息使用严格 ID 游标

**问题**：过滤条件为 `m.id > after_id`，但旧查询按 `timestamp, id` 排序。当历史时间戳乱序且分页受限时，前端推进 ID 游标后可能永久跳过较小 ID 的消息。

**决策**：

- SQLite 增量查询严格 `ORDER BY m.id ASC`
- API 返回 `next_after_id` 和 `has_more`
- 前端连续读取后续批次，直到 `has_more=false`

时间戳仅用于展示，不参与增量游标推进。

---

## 2026-07-10: 发送成功必须是显式真值

**决策**：发送链路只有在底层结果明确返回 `success is True` 时才算成功。缺失、`false`、异常、非 2xx 均作为失败处理。

- 单发失败由 API 返回 502 和可重试标记
- 前端失败消息保留原文、目标与发送模式，允许原地重试
- 群发返回每个目标结果以及成功/失败统计，不再总是返回成功

---

## 2026-07-10: 左滑操作与纵向滚动手势分离

**决策**：会话操作层放在内容层下方，默认不可见。手势移动超过阈值后先锁定方向：横向才更新位移，纵向交还列表滚动。

同时要求：

- `touch-action: pan-y`
- 同时只允许一行展开
- 滑动完成后的 click 不打开会话
- 删除需要用户确认，接口失败必须反馈
