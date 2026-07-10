# 2026-07-10 消息页稳定性与微信式布局修复计划

## 关联规格
- `FR-MSG-002`：消息增量更新不得造成全页重载。
- `FR-MSG-007`：查看历史时新消息不得强制滚底。
- `UX-001`：聊天页面采用微信式结构，不使用后台管理式工具条。
- `UX-005`：聊天页仅保留当前联系人和高频发送动作。
- `UX-008`：移动端 safe area、reduced motion 与稳定滚动。
- `SDD-P1-04`：聊天头部收敛为返回、名称、状态和单一“…”入口；Emoji/AI 模式进入更多面板。
- `SDD-P2-01`：聊天容器尺寸和滚动稳定。

## 已复现证据
- 生产移动视口 390×844，打开首条聊天并连续采样 12 秒。
- 第 20 个采样点消息行从 80 瞬间变为 0、骨架屏重新出现、滚动从 12697 跳到 0，随后恢复。
- 同期 `/api/settings`、会话列表、dashboard、当前聊天详情被重复请求。
- 当前聊天首次加载 80 条消息时生成 79 条翻译行，DOM 高度约 13322px。

## 根因假设
1. `useAccountsController` 每 3 秒创建新的 accounts 数组；`fetchConversationsPage` 依赖该数组，导致 callback 身份变化。
2. `refreshWorkspace` 随之变化，使登录初始化 effect 重新执行并再次刷新 settings/workspace。
3. settings 对象刷新后，`ChatPane` 初始加载 effect 因依赖整个 `uiSettings` 对象而清空 messages、显示 skeleton、滚动归零，形成周期性闪烁。
4. 聊天头部存在头像和两个动作按钮，输入区把 AI 模式与 emoji 长期展开，偏离微信“标题 + … / 输入 + 更多面板”布局。

## TDD步骤
1. RED：增加前端回归测试，要求工作区轮询 callback 不依赖 accounts 数组；ChatPane 初始加载只依赖稳定会话身份和默认模式；聊天头部只有单一更多按钮；emoji/AI 工具位于可折叠更多面板。
2. GREEN：稳定 callback 与 effect 依赖，避免 silent poll 重置消息。
3. GREEN：重构聊天头部、消息行、输入区为微信式结构，补齐发送方头像和更多面板。
4. REFACTOR：统一 CSS，减少动画与布局跳变，保持移动安全区。
5. 验证：前端测试/build、Python/Bridge回归、生产浏览器连续采样不再出现 rows 80→0、桌面/移动截图和资源哈希。
