# 迁移与上线规格

## 1. 目标

将当前依赖 Hermes profile/gateway/state.db 的生产系统迁移到独立 API、Bridge、Worker 和业务数据库，同时保证：

- 当前服务不中断；
- 历史数据可迁移；
- 不发生重复自动回复；
- 可在一个部署窗口内回滚；
- Hermes 仅在切换完成前作为 Legacy 运行时保留。

## 2. 阶段

### MIG-001：独立部署配置合同

- 状态：`In Progress`（systemd/static assets 仅为合同草案；独立 API 运行时已开始实现，但未完成生产安装或切换验收）。
- API unit 必须从 `/opt/whatsapp-chat-system` 启动 `serve`，不带 `--profile`；运行目录、`DATABASE_URL`、`WHATSAPP_BRIDGE_INTERNAL_TOKEN` 均来自独立 systemd 配置合同。
- Bridge V2 unit 必须从 `/opt/whatsapp-chat-system/bridge` 启动，固定 loopback `127.0.0.1:3100`，并将 credentials/spool/media 限定在 `/var/lib/whatsapp-chat-system/bridge`。
- token、密码和数据库连接串仅放入 `/etc/whatsapp-chat-system/{api,bridge}.env` 等受控主机文件，不进入仓库、SDD 或 unit 内容。

退出条件：仓库契约测试通过；生产安装留待 MIG-8，且不得借此 task 触碰现有服务。

### MIG-002：切换与回滚边界

- 状态：`In Progress`。
- Legacy gateway、Legacy Bridge、Hermes profile 与旧 `state.db` 在历史导入、独立 API/Bridge live+ready、数据库迁移和关键数据面验证完成前保持可回滚，不得因安装新 unit 而停止。
- 只有完成只读导入报告、Bridge V2 live readiness 和受控切流批准后，才可停止同账号 Legacy 自动处理；停止 legacy 服务不是本 task 的副作用。
- 任何 readiness、导入、事件积压或关键收发异常均按第 5 节回滚，保留 standalone 数据库和 spool 现场，不删除 profile 归档。

### MIG-0：基线冻结

- 状态：`Approved`
- 记录当前测试、进程、端口、资源 hash、数据库 schema 和数据统计；
- 创建只读备份；
- 引入 `RUNTIME_MODE=legacy|standalone`；
- 默认仍为 legacy。

退出条件：基线测试和恢复方法已验证。

### MIG-1：问鼎 AI 独立配置

- 状态：`Approved`
- AI 配置来自环境/独立 settings；
- 默认 URL/model 按 SDD；
- Legacy WhatsApp 链路不变。

退出条件：无 Hermes config 时 AI Provider 单测、mock 集成测试通过。

### MIG-2：新业务数据库

- 状态：`Approved`
- 部署 schema/migrations；
- 建 accounts/contacts/conversations/messages/outbox 等；
- 暂不切换前端读路径。

退出条件：账号隔离、幂等、状态机和 migration 测试通过。

### MIG-3：Bridge V2 单账号影子运行

- 状态：`Approved`
- 使用测试 WhatsApp 账号；
- 验证 QR、重启恢复、入站 webhook、出站发送；
- 禁止与 Legacy 对同一账号同时自动回复。

退出条件：稳定运行观察窗口内无丢事件和重复发送。

### MIG-4：Bridge V2 多账号

- 状态：`Approved`
- 至少两个测试账号；
- 验证隔离、重连、登出、发送路由、spool 恢复。

退出条件：多账号 E2E 全通过。

### MIG-5：Worker 与任务切换

- 状态：`Approved`
- 新发送进入 Outbox；
- 定时和群发进入 Worker；
- Legacy 同步发送关闭。

退出条件：Worker 重启、重试、取消、幂等验证通过。

### MIG-6：历史数据导入

- 状态：`Approved`
- 只读读取旧 Hermes 数据；
- 映射到 legacy account；
- 输出导入报告；
- 对关键联系人/会话抽样比对。

退出条件：记录数和校验报告符合预期，无凭据被复制到 Git。

### MIG-7：前端切换 API V1

- 状态：`Approved`
- 账号中心、账号筛选、消息状态、任务进度连接新 API；
- Legacy API 保留短期兼容；
- feature flag 支持快速回退。

退出条件：桌面/移动端主链路 E2E 通过。

### MIG-8：生产切换

- 状态：`Approved`
- 停止同账号 Legacy 自动处理；
- 启用 standalone API/Bridge/Worker；
- 观察消息、任务、AI、账号状态和错误指标；
- 不立即删除 Hermes profile。

退出条件：观察窗口通过，回滚未触发。

### MIG-9：Hermes 运行时退役

- 状态：`Approved`
- 停止 Hermes gateway；
- 移除生产命令中的 `--profile` 和 `hermes send` fallback；
- 旧 profile 变为只读归档；
- 文档标记 Standalone 为唯一生产模式。

退出条件：服务器没有 Hermes gateway/CLI 时核心功能仍正常。

## 3. 双写和防重复原则

- 同一 WhatsApp 账号不得同时由 Legacy 与 Standalone 自动发送；
- 入站事件使用 `event_id` 幂等；
- 消息使用 `(account_id, wa_message_id)` 幂等；
- 出站使用 `Idempotency-Key` + outbox 唯一键；
- 导入器使用 `migration_batch_id` 和 source key；
- 影子模式只观察或写新库，不发送真实回复。

## 4. 回滚条件

任一情况触发回滚评估：

- 入站事件持续丢失或积压；
- 跨账号串消息或误发；
- 重复发送；
- Outbox 大量 stuck；
- Bridge 多账号异常导致主进程频繁退出；
- AI key 泄露或权限越权；
- 新数据库不可恢复；
- 关键 E2E 失败。

## 5. 回滚步骤

1. 暂停 Standalone Worker 领取新任务；
2. 禁止 Bridge V2 发送；
3. 保留新库和 spool，不删除失败现场；
4. 恢复 Legacy gateway/Bridge；
5. 将前端/API feature flag 切回 legacy；
6. 验证账号在线和单发；
7. 对回滚窗口内消息做幂等补偿；
8. 记录事故、修 SDD/测试后再尝试切换。

## 6. 生产验证清单

- API `/health/live`、`/health/ready`；
- Bridge `/health/live`、`/health/ready`；
- Worker heartbeat；
- 数据库 migration head；
- Redis/队列；
- 每个账号状态、手机号和最后连接；
- 两账号分别收发测试消息；
- AI preview 显示问鼎 AI 和正确模型；
- 失败消息正确进入 failed/retry；
- 定时消息真实到点发送；
- 群发进度、取消和逐项结果；
- 插件关闭后对应后端 hook 不执行；
- 日志和前端不出现 key/token/session；
- 首页、JS、CSS、深链路均为 200。

## 7. 数据保留

- Hermes profile 在退役后至少保留一个约定观察周期，只读且限制权限；
- WhatsApp session 备份必须加密，禁止进入普通源码备份；
- 数据库按生产恢复目标配置备份和恢复演练；
- spool/outbox 清理只处理已确认完成且超过保留期的数据。
