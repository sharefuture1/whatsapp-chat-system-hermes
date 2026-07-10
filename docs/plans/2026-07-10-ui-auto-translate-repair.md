# 2026-07-10 页面样式与自动翻译真实接线修复计划

关联需求：SDD-P1-05、SDD-P1-06、SDD-P1-04、SDD-P2-01、SDD-P2-06。

## 根因证据

1. 生产设置中插件和消息自动翻译开关均为 true，但 `/api/v1/ai/settings` 返回 `api_key_configured=false`；真实老挝语翻译探针返回 `configuration_error`。
2. 翻译失败被 ChatPane 的空 `catch` 静默吞掉，页面既不显示失败，也不引导配置 AI。
3. `ChatPane` 只读取 `message_ops.auto_translate`，没有使用插件与全局 AI 可用性组合后的有效状态。
4. `_ensure_message_translations` 未检查插件开关，且仍把 message ID 强制转为 int；`Unknown` 在翻译端点被直接跳过。
5. styles.css 存在重复规则、未定义变量和 31 个 JSX 已使用但 CSS 未定义的账号/页面类；桌面端仍把移动 TabBar 拉满全屏，页面缺少统一最大宽度；移动插件内容底部可能被 TabBar 遮挡。

## TDD 步骤

1. RED：补自动翻译插件门禁、Unknown 文本进入 AI、字符串消息 ID、Provider 未配置返回清晰错误测试。
2. GREEN：统一后端有效状态与翻译错误契约。
3. RED：补前端有效自动翻译状态、错误可视化和关键 CSS 契约测试。
4. GREEN：ChatPane 使用 App 传入的有效状态并显示失败；插件页显示阻塞原因；补齐缺失页面样式和响应式规则。
5. 浏览器：桌面/390px 逐页截图、横向溢出、滚动高度、底栏遮挡、控制台错误验收。
6. 全量门禁、真实 AI 探针、部署、文档、提交推送。
