# 第一轮 P0 修复：代码验收记录

状态：Implemented / 代码验收通过；Production Verified 未完成。
基线：`codex/p0-hardening-tauri2` 的 `53b8d6bcb86cabe6a96907a63958cbaff878a32d`。
修复代码：`47438b30259a74989889a07255d93c6062b3a5b6`；PR #4。

本记录更新 PROJECT_MEMORY / TODO_AGENT / DECISIONS / CHANGELOG_AGENT 中本轮“等待完整 CI 验收”的阶段状态。旧的生产记录不能作为本轮部署证明。

## 修复范围

- SEC-CACHE-001：延迟缓存写入绑定不可变用户范围和 generation；退出、切换用户和删除会话后取消旧写入。旧 API 响应及迟到 401 不影响新会话；修改前后的 GET 缓存失效；请求 deadline 包括读取响应体，主动取消与超时分开。
- SEC-AUTH-015：强制改密标记持续到改密成功；API 阻止受限会话访问业务功能，浏览器只显示改密页面；成功后撤销该用户全部会话并重新登录。未标记的现有用户不被强制改密。
- DATA-004 / TX-TRANS-001：入站、批次接口与 Dispatcher 的译文复用限制在账号内；共享精确原文 SHA-256；旧版本 completed 不抑制新原文；全缓存命中提交后才返回；重用已有失败记录避免唯一键冲突。
- QA-ROUND-001：新增 10 个后端回归、8 个 Web 回归；真实 Chromium 测试强制改密。永久 CI 将 Python pytest 和格式检查拆开，二者均保留失败门禁。

## 实际执行证据

GitHub Actions：
https://github.com/sharefuture1/whatsapp-chat-system-hermes/actions/runs/34625564338

Job：
https://github.com/sharefuture1/whatsapp-chat-system-hermes/actions/runs/34625564338/job/103349700214

锁定环境：Python 3.11.16、uv 0.9.25、Ruff 0.15.21、Node 20.20.2；uv sync --locked，npm ci。

| 检查 | 实际结果 |
| --- | --- |
| Python 完整回归 | 384 passed / 7 skipped / 1 warning |
| Web 完整回归 | 138 passed / 0 failed |
| Bridge 完整回归 | 87 passed / 0 failed |
| Bridge 语法检查 | 通过 |
| 锁定 Ruff 检查与格式校验 | 通过 |
| Browser 生产构建 | 通过 |
| Chromium 390×844 | 强制改密流程通过 |
| Chromium 1366×900 | 强制改密流程通过 |
| Tauri 前端构建、shell 配置与 CLI | 通过 |

7 个 skipped 为未配置可丢弃 PostgreSQL 测试库的专项；没有声称 PostgreSQL 实库验收通过。浏览器测试真实运行 Chromium，但 API 被测试夹具拦截，不是生产后端或真实 WhatsApp 收发测试。Tauri 验收不包含本轮真实桌面安装包运行。

Browser 构建：`index-BMYqwtrw.js`、`index-BTLsauWb.css`。Tauri 前端：`index-DJ8RDo9d.js`。这些是 CI 产物，不是线上部署版本。

## 未完成与发布边界

- gcptw `open_workspace` 返回 `FORBIDDEN: This conversation does not support developer MCPs`。未连接服务器执行命令，未部署、重启、迁移数据库，未修改密钥或 WhatsApp session，未开启客户自动回复。
- 未创建每 6 小时自动开发、同步、部署任务。一次性 CI 验证不是定时优化。
- 历史缓存/历史译文未做生产清理；本轮修复防止新的越界复用，不声称消除已经产生的历史污染。
- 安装时 npm audit 提示 Web 6 项（2 moderate / 4 high）、Bridge 1 high；本轮未修改依赖，需另行检查具体 advisory、运行时可达性和兼容升级。此提示不等于已经确认生产可利用。

## 接续优先级

1. 完整 UI 会话状态清理（账号列表、选择状态等）和多用户浏览器回归；核查依赖风险。
2. 后端翻译单入口、统一启停策略、原子任务领取/租约与有界重试。
3. 消息封装解析、事件投递身份/业务身份拆分、游标分页与历史覆盖范围。
4. 自动回复配置解析统一、Outbox 租约与发送结果不确定处理。
5. gcptw 可用后，按 wheel + Browser dist 的版本核验/备份/回滚流程部署，保留数据库与账号会话；真实端点验收后才标 Production Verified。

临时源码快照、补丁传输文件和具有仓库写权限的一次性验证 workflow 已从最终源码树删除；长期 CI 仅 contents: read。
