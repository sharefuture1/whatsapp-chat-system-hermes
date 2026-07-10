# SDD-P0-02 实施计划：新业务数据库与账号隔离

> 状态：Ready
> 需求：DATA-001~007、FR-ACC-003、FR-CON-003
> 前置：SDD-P0-01 已 Implemented；当前生产仍为 Legacy，本阶段不切换生产读写源。

## 目标

在项目内建立独立业务数据库基线，使用 SQLAlchemy 2 + Alembic，开发/测试支持 SQLite，生产支持 PostgreSQL。首批表必须强制 `account_id` 隔离，并通过迁移、幂等和跨账号测试。

## 范围

首批实现：

- `whatsapp_accounts`
- `contacts`
- `conversations`
- `messages`
- `ai_profiles`
- `contact_ai_overrides`
- `whatsapp_events`
- `outbox_messages`

本阶段不实现：

- Bridge V2 socket/QR；
- Worker claim 和真实发送；
- 旧 Hermes `state.db` 正式迁移；
- Web API 全量切换；
- PostgreSQL 生产部署。

## 技术决策

- ORM：SQLAlchemy 2.0 typed declarative models。
- Migration：Alembic；禁止应用启动时隐式破坏性建表。
- 主键：跨 SQLite/PostgreSQL 统一使用字符串 UUID（36 chars），由应用生成。
- 时间：UTC timezone-aware datetime；SQLite 保存兼容值，领域层统一 UTC。
- JSON：SQLAlchemy JSON，仅保存 tags/metadata/media/usage 等扩展字段。
- Enum：首版以受约束字符串列实现，避免 SQLite/PostgreSQL enum migration 差异。
- DB URL：`DATABASE_URL`，默认仅开发用途 `sqlite:///./data/whatsapp-chat-system.db`。
- Legacy `storage.py` 保持不动，新增 `db/` 包；通过 runtime feature flag 后续切换。

## 文件

创建：

- `alembic.ini`
- `migrations/env.py`
- `migrations/script.py.mako`
- `migrations/versions/0001_standalone_core.py`
- `src/whatsapp_chat_system/db/__init__.py`
- `src/whatsapp_chat_system/db/base.py`
- `src/whatsapp_chat_system/db/models.py`
- `src/whatsapp_chat_system/db/session.py`
- `src/whatsapp_chat_system/db/repositories.py`
- `tests/test_db_migrations.py`
- `tests/test_db_account_isolation.py`
- `tests/test_db_idempotency.py`

修改：

- `pyproject.toml`：增加 SQLAlchemy、Alembic；测试增加必要依赖。
- `src/whatsapp_chat_system/settings.py`：增加独立数据库设置，不读取 Hermes profile。
- SDD/四文件：状态与验证记录。

## TDD 任务

### Task 1：数据库设置与 Session

RED：

- 默认 SQLite URL 可加载；
- `DATABASE_URL` 可覆盖；
- 不依赖 Hermes profile/config；
- SQLite 自动启用 foreign keys；
- session commit/rollback/close 生命周期正确。

GREEN：实现 `DatabaseSettings`、engine/session factory。

### Task 2：核心 Schema 与 Alembic

RED：

- `alembic upgrade head` 创建 8 张首批表；
- 必需外键、唯一约束和索引存在；
- `alembic downgrade base` 可完全回退；
- 再次 upgrade 可成功。

GREEN：实现 models、metadata、0001 migration。

### Task 3：账号隔离 Repository

RED：

- 账号 A/B 可保存相同 `remote_jid`；
- 同账号重复 `remote_jid` 被唯一约束拒绝；
- repository 查询必须传 `account_id`；
- 账号 A 查询不能返回账号 B contact/conversation/message；
- conversation 与 contact 的 account_id 不一致时拒绝写入。

GREEN：实现 scoped repositories，不暴露无 scope 的联系人/会话/消息查询。

### Task 4：消息与事件幂等

RED：

- 同账号相同 `wa_message_id` 只能入库一次；
- 不同账号相同 `wa_message_id` 可并存；
- `wa_message_id=NULL` 的本地 queued 消息可多条存在；
- `event_id` 全局幂等；
- outbox `idempotency_key` 全局唯一；
- 写入重复项返回 existing/duplicate 结果，而不是生成第二条业务消息。

GREEN：实现 repository 幂等接口和约束错误映射。

### Task 5：集成与兼容

RED：

- Legacy `storage.py` 现有测试保持通过；
- 新 DB 包不要求存在 Hermes `state.db`；
- application import 不会自动执行 migration；
- PostgreSQL dialect 编译关键索引/约束无 SQLite 专属 SQL。

GREEN：完成兼容性修正和说明。

## 门禁

- 每个 Task 必须先看到预期 RED，再写实现。
- 目标 DB 测试全部通过。
- `alembic upgrade head → downgrade base → upgrade head` 真实执行通过。
- 全量 `pytest -q` 通过。
- 前端 `npm run build` 和 ChatSync 保持通过。
- `python -m py_compile ...`、`git diff --check` 通过。
- 规格审查 PASS 后再做代码质量/安全审查。
- 未连接生产 PostgreSQL、未切换 8792 数据源时，状态最多为 `Implemented`。

## 验收映射

- 两账号相同 JID 可并存 → Task 3。
- 查询无跨账号泄漏 → Task 3。
- 重复 WhatsApp message ID 幂等 → Task 4。
- Alembic upgrade/downgrade → Task 2。
- SQLite/PostgreSQL 可移植 → Task 1、2、5。
