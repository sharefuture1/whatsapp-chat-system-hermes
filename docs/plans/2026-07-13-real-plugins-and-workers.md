# 2026-07-13 — 完善插件中心与可观察性

## 范围（本轮）

由于真正接通 Outbox + Worker 涉及 Bridge V2、SQLAlchemy Job 表、异步循环、限速调度等多项 SDD-P0-05/06/07 工作，
本轮聚焦“前端可见 + 后端可观察 + 快捷入口”的层面，定时/群发继续以 503 表现直到 SDD-P0-06/07 接入 Outbox。
Outbox / 调度实现保留给 `docs/plans/2026-07-14-outbox-scheduler.md` 后续 PR。

## 目标

1. 插件目录每个条目都必须真实携带 `available / unavailable_reason / status_when_on / hooks`。
2. 受控 AI 人设、自动翻译、AI 智能回复（preview）、记忆、统计插件在前端显示其当前真实启用状态。
3. 定时/群发插件显示“Worker 未接通”原因，并提供“打开工具中心”入口（独立 CenterPage，列出现有任务清单）。
4. 插件切换（toggle / remove）后立即持久化；前端无须刷新。
5. 统计插件 UI 真实从 `/api/dashboard` 拉取细分数字。

## 后端改动

- `src/whatsapp_chat_system/web_api.py`：
  - `PLUGIN_CATALOG` 改为动态 `available / unavailable_reason / status_when_on`，由真实 hook 状态生成；
  - `/api/plugins` 列表同时返回 `available / unavailable_reason / status_when_on` 与插件 toggle 真实状态；
  - `/api/dashboard` 扩展 `stats`，加入 `unread_messages / pending_replies / sent_messages / avg_response_seconds`；
  - 新增 `/api/v1/plugins/{id}/detail` 返回扩展状态。
- `src/whatsapp_chat_system/web_api.py` 定时/群发保持 503，但 `GET /api/schedule` 与 `GET /api/broadcast` 仍返回 `items: []`，前端 CenterPage 用它判断 “是否有任务”。
- 端到端测试 `tests/test_plugins_dynamic_state.py`：验证 available / reason / status_when_on；toggle 后持久化。

## 前端改动

- `web/src/components/PluginCenterPage.jsx`：
  - 每个插件显示 `status_when_on` 与 `unavailable_reason`；
  - 启停按钮真实生效并立即更新；
  - 定时/群发插件在 `unavailable_reason` 后显示“打开任务中心”按钮（跳转到新的 SchedulerCenter / BroadcastCenter）。
- 新增 `web/src/components/SchedulerCenterPage.jsx`：列出当前定时任务（来源 `/api/schedule`）、创建向导（暂以占位提示 Worker 未接通）、取消按钮。
- 新增 `web/src/components/BroadcastCenterPage.jsx`：列出群发任务（来源 `/api/broadcast`）、创建向导。
- `web/src/components/DiscoverPage.jsx` 仍只展示概览 + 受控 AI 人设。

## 风险

- `PLUGIN_CATALOG` 字段扩展需确保旧测试不再依赖 `available` 字段缺失。
- 切换插件状态会写 `web_settings.plugins`，老用户已有持久化不会丢。
