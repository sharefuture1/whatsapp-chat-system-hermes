# Bridge V2 与多账户账号中心实施计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 建立不依赖 Hermes gateway/CLI 的 WhatsApp Bridge V2 基础，并交付由真实账号 API 驱动的多账户账号中心 UI。

**Architecture:** FastAPI 作为业务真源，SQLAlchemy `whatsapp_accounts` 保存账号状态；独立 Node/Baileys Bridge 通过 loopback + internal token 管理每个 `AccountSession`。本阶段先完成可测试的账号管理、QR/状态代理和微信式账号中心，Bridge V2 采用 `AccountManager Map<account_id, AccountSession>`，即使真实验收先使用一个账号，也不写单例架构。

**Tech Stack:** FastAPI、SQLAlchemy 2、Alembic、React/Vite、Node.js `node:test`、Baileys、pytest。

**绑定需求:** FR-CORE-001~005、FR-ACC-001~008、SEC-002/004~006、UX-001~008、API 账号契约、SDD-P0-03、SDD-P1-01。

---

## Task 1：修正数据库迁移与 AI runtime schema 漂移

**Files:**
- Modify: `src/whatsapp_chat_system/db/models.py`
- Create: `migrations/versions/0002_ai_runtime_timeout_retry.py`
- Test: `tests/test_db_migrations.py`

**RED:** 增加 migration round-trip 测试，断言 `ai_runtime_settings` 存在 `timeout_seconds`、`max_retries`。

**GREEN:** 模型和 migration 增加两列，默认 90/2，满足现有 RuntimeAISettingsManager。

**Verify:**
```bash
.venv/bin/pytest tests/test_db_migrations.py -q
```

## Task 2：账号 Repository / Service

**Files:**
- Create: `src/whatsapp_chat_system/accounts/__init__.py`
- Create: `src/whatsapp_chat_system/accounts/repository.py`
- Create: `src/whatsapp_chat_system/accounts/service.py`
- Test: `tests/test_accounts_service.py`

**RED cases:**
- 创建账号生成 UUID 和受控 `session_ref`，不包含 Hermes profile；
- 第一个账号自动成为主账号；
- 设置新主账号时原主账号原子取消；
- 同名允许/不允许规则按规格明确；
- 停用不删除 session；
- 删除确认名错误拒绝；
- A 操作不影响 B。

**GREEN:** 实现事务化 CRUD、状态更新和安全序列化。

## Task 3：Bridge Client 契约

**Files:**
- Create: `src/whatsapp_chat_system/bridge/__init__.py`
- Create: `src/whatsapp_chat_system/bridge/client.py`
- Test: `tests/test_bridge_client.py`

**RED cases:**
- 所有请求带 `X-Internal-Token`；
- timeout/401/503 映射结构化错误；
- send 200 但无真实 `message_id` 判失败；
- QR 410 保持 `qr_expired`；
- URL 不允许外部 host 默认值。

**GREEN:** requests/httpx client，明确连接/读取超时，不回退 Hermes CLI。

## Task 4：FastAPI v1 账号 API

**Files:**
- Create: `src/whatsapp_chat_system/api/v1/accounts.py`
- Modify: `src/whatsapp_chat_system/web_api.py`
- Test: `tests/test_accounts_api.py`

**RED cases:**
- GET/POST/PATCH accounts；
- connect 返回 202 但不提前标记 online；
- QR 只在 qr_pending 返回；
- logout 不删除业务数据；
- DELETE 需要 `confirm_name`，`delete_session` 独立；
- 响应不返回真实 session 路径或凭据；
- 无 Hermes profile 时账号 API 可启动。

**GREEN:** 将 v1 router 接入现有认证中间件；Bridge 不可达时返回结构化 retryable error。

## Task 5：Bridge V2 Node 基础

**Files:**
- Create: `bridge/package.json`
- Create: `bridge/src/config.js`
- Create: `bridge/src/account-manager.js`
- Create: `bridge/src/account-session.js`
- Create: `bridge/src/server.js`
- Create: `bridge/tests/*.test.js`
- Modify: `.gitignore`

**RED cases:**
- 同账号并发 connect 只创建一个 socket；
- A/B session 目录隔离；
- logged_out 不退出 Node 主进程；
- QR 生命周期和过期；
- send 无 message ID 失败；
- internal token 认证；
- live/ready 分离；
- account ID 路径穿越拒绝。

**GREEN:** 使用 injectable fake Baileys factory 完成内核；复制协议逻辑时注明来源，禁止修改系统 Hermes 安装目录。

**规格审查修复 RED/GREEN（2026-07-10）：**
- RED：在原 19 passed 基线上先新增 QR `qr_data_url`、同帧 QR/connecting 优先级、close generation 失效、fake scheduler 指数退避、stop/logout/delete 取消 timer、401/440 分类、全响应 `X-Request-ID` 回显/生成测试；首次运行 26 tests 中 9 failed，失败点与审查阻断项一致。
- GREEN：实现账号级可注入 scheduler/jitter 的指数退避，close 立即失效旧 generation，`loggedOut=401` 且 `connectionReplaced=440` 重连，QR 契约改为 `qr_data_url`，所有 Bridge 响应附请求 ID；`npm test` 26 passed，`npm run lint` 通过。
- Scope：仅修改 Task 5 的 `bridge/src`、`bridge/tests` 与本计划记录，未实现 Task 6 event spool/webhook。

**代码质量审查 Important 修复 RED/GREEN（2026-07-10）：**
- RED：新增 delete/create/connect 并发竞态、QR 过期重复读取、canonical/legacy token 冲突、HTTP timeout、readiness、`closeAll` 与 SIGTERM/SIGINT 测试；首次运行 33 tests 中 8 failed。
- GREEN：按账号生命周期 Promise 串行化删除与后续 create/connect；QR 过期保留稳定 flag 并将状态归一为 `offline/has_qr=false`；`WHATSAPP_BRIDGE_INTERNAL_TOKEN` 为权威且冲突 fail-closed；补 server timeout、manager readiness/closeAll 和进程优雅关闭。
- Verify：`npm test` 33 passed；`npm run lint` 通过；`npm audit --omit=dev` 为 0 vulnerabilities；未进入 Task 6。

## Task 6：持久化 Event Spool 和内部事件接收

**Files:**
- Create: `bridge/src/events/file-spool.js`
- Create: `bridge/src/events/event-sink.js`
- Create: `src/whatsapp_chat_system/events/whatsapp.py`
- Create: `src/whatsapp_chat_system/api/internal/whatsapp_events.py`
- Test: `bridge/tests/event-sink.test.js`
- Test: `tests/test_whatsapp_events.py`

**RED cases:**
- webhook 500/timeout 保留 spool；
- 重启 replay；
- duplicate=true 后完成 spool；
- event_id 幂等；
- A event 不更新 B；
- message.upsert 事务化 upsert contact/conversation/message。

**完成记录（2026-07-10）：**
- RED→GREEN：实现 FileSpool/EventSink、FastAPI internal receiver、Alembic `0003`，覆盖 500/timeout/401 保留、422 dead-letter、restart replay、duplicate、identity conflict、账号隔离、事务落库与单调状态/回执。
- 审查修复：按 sequence claim；旧 event payload hash 回填；真实 startBridge 自动 replay；sent/delivered/read/failed 接线；重复 receipt 独立身份；同账号唯一 sink owner；QR 过期/stop 离线事件；安全错误脱敏。
- 安全：loopback、token fail-closed、Host 防 DNS rebinding、请求 ID、目录 `0700`、不记录 QR/raw credential。
- 验证：Bridge 63 passed、lint 通过、audit 0；Python 118 passed；Alembic upgrade→downgrade→upgrade；V2 3100 无真实账号影子 live/ready/auth/create/status/stop 通过。
- 状态：代码为 `Implemented`；真实扫码、真实收发/回执、双账号在线仍待 Task 11 使用测试账号验收。

## Task 7：前端账号领域控制器

**Files:**
- Create: `web/src/accounts/accountState.js`
- Create: `web/src/accounts/useAccountsController.js`
- Create: `web/tests/accountState.test.js`
- Modify: `web/src/api.js`

**RED cases:**
- account A 事件不更新 B；
- 重复/迟到事件不覆盖新状态；
- 删除后忽略迟到事件；
- QR 请求切换账号防串线；
- connect 202 不显示 online。

## Task 8：微信式 Account Center UI

**Files:**
- Create: `web/src/components/AccountCenterPage.jsx`
- Create: `web/src/components/AccountStatusBadge.jsx`
- Create: `web/src/components/AccountQrPage.jsx`
- Modify: `web/src/components/MePage.jsx`
- Modify: `web/src/App.jsx`
- Modify: `web/src/styles.css`
- Modify: `web/src/i18n.js`

**Behavior:**
- “我”页入口显示在线数/总数；
- 全屏账号列表、创建、QR、重连、登出、停用、删除；
- 不出现 Hermes/profile/path/CLI；
- 高危操作区分停用、登出、删除 session；
- 移动端 safe area、44px 触控、aria-live、reduced motion；
- 全部可见文案进入四语言 i18n。

## Task 9：移除旧伪平台账号 UI

**Files:**
- Modify: `web/src/components/SettingsPanel.jsx`
- Modify: `web/src/components/MePage.jsx`
- Modify: `web/src/i18n.js`

**RED:** 静态测试确认账号页面不包含 `Hermes profile`、`profile_path`、`connect command`。

**GREEN:** 删除 `PLATFORM_OPTIONS/makeWorkspace/commandFor` 和 workspaces 编辑器；账号管理只走真实 v1 API。

## Task 10：账号筛选与会话身份准备

**Files:**
- Modify: `web/src/App.jsx`
- Modify: `web/src/components/ChatList.jsx`
- Create: `web/src/components/AccountSwitcher.jsx`
- Test: `web/tests/accountConversationIdentity.test.js`

**Scope:** 本阶段只在新 v1 会话数据存在时启用，Legacy 会话保持兼容但明确标记单账号。新路径使用 `conversation.id` + `account_id`，禁止把 `user_id` 当全局主键。

## Task 11：完整门禁、影子部署和真实验收

**Commands:**
```bash
.venv/bin/pytest -q
cd web && node --test tests/*.test.js && npm run build
cd bridge && npm test
python -m compileall src
```

**Shadow verification:**
- Bridge V2 独立端口/测试账号；
- 默认不启用自动回复；
- 不停止 Legacy Hermes gateway；
- 验证创建、QR、扫码、Bridge 重启 session 恢复、入站 spool、真实 send message ID；
- 通过后才更新 SDD 状态为 Implemented/Verified。

**禁止:**
- 用假 QR、固定在线状态或纯前端 mock 声称完成；
- 在真实 Bridge 未验收前停止 Hermes gateway；
- 把 `connect` 的 HTTP 202 当成 online；
- 把 API key、internal token、session credentials 写入 Git。
