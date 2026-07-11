# 2026-07-11 通讯录与会话生命周期分离 — RED 记录

关联需求：`FR-MSG-008`、`FR-CON-001`、`SEC-005`。

## 目标

- Legacy `/api/contacts` 复用会话摘要作为联系人来源，但不应用 `chat_ops.deleted` 过滤，并返回 `conversation_deleted`；原 `/api/conversations` 继续隐藏删除会话。
- V1 删除会话只设置 `conversations.deleted_at`，不删除 Contact、Message 或历史；联系人接口仍返回联系人，并允许确保/恢复会话。
- 前端通讯录独立读取 Legacy `/api/contacts`；联系人无可见会话时可恢复/确保会话并进入聊天。
- 删除动作按会话 `source` 分流，并始终以 `conversation_key` 判断当前选择。

## RED 测试

新增后端失败测试：

1. Legacy 删除会话后：`/api/conversations` 不包含该 JID，`/api/contacts` 仍包含并标记 `conversation_deleted=true`。
2. Standalone `DELETE /api/v1/conversations/{id}` 后：列表隐藏会话，Contact 与 Message 保留；`POST /api/v1/contacts/{contact_id}/conversation` 恢复同一会话及历史。
3. Standalone 无会话联系人：ensure 接口创建空会话；错误账号/contact scope 不得创建或恢复其他账号数据。

新增 Web 失败测试：

1. 联系人点击 helper：Legacy 隐藏会话先调用 restore，刷新后选择 `legacy:<jid>`；Standalone 无会话先 ensure，刷新后选择 `standalone:<id>`。
2. 删除 helper：Legacy 使用裸 JID 调 `/chat/delete`；Standalone 使用 conversation UUID 调 V1 DELETE；选中比较 `conversation_key`。
3. App 工作区独立请求 `/contacts`，`buildContacts` 不再消费 Legacy conversations；ContactsPage 不因 `conversation_id` 为空禁用。

## 首次 RED 结果

- `./.venv/bin/pytest -q tests/test_contact_conversation_lifecycle.py` → **3 failed**：Legacy `/api/contacts` 命中 SPA（路由不存在）；V1 DELETE 与 ensure 均为 `405 Method Not Allowed`。
- `cd web && node --test tests/conversationLifecycle.test.js` → **failed**：`web/src/conversationLifecycle.js` 不存在。

RED 已在任何业务实现前真实保存。