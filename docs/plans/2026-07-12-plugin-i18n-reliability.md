# 2026-07-12 插件目录与四语言可靠性计划

- 关联规格：`SDD-P1-06`、`SDD-P2-05`、`SDD-P2-06`
- 状态：In Progress

## 目标

1. 所有用户可见的插件目录状态可翻译，并完整覆盖 `en`、`zh`、`th`、`lo`。
2. 插件目录准确表达运行现实：只有 `available=true` 的插件可切换；不可用插件显示原因，不显示删除/禁用等误导操作。
3. 刷新、筛选、加载和失败状态必须明确，避免空白卡片、重复请求或把失败当作“无插件”。
4. 定时与群发的 UI 继续标记为未接入可靠 Worker；不改变后端能力声明，不伪装成功。

## RED → GREEN

1. 新增 Web 静态契约测试：四语言 key 集合严格一致；`t()` 不将空字符串当作有效翻译；插件中心具备 busy/error/retry 和 unavailable guard。
2. 先运行测试记录失败。
3. 增补 i18n key 与运行时回退。
4. 重构 `DiscoverPage` 和 `ToolsPanel`：共享分类元数据、切换 busy guard、不可用原因、禁用非真实操作。
5. 执行 Web / Python / Vite / 线上静态资源门禁。

## 不在本轮范围

- 不实现 `schedule` / `broadcast` 的真实 Outbox Worker；该任务仍由 `SDD-P0-06` / `SDD-P0-07` 约束。
- 不修改 AI Provider、认证和 CORS。
