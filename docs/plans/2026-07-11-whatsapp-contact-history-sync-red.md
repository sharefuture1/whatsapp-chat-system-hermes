# FR-CON-011 WhatsApp 联系人、聊天与近期历史同步 — RED 记录

日期：2026-07-11

## 范围

- Bridge 开启 Baileys 有界历史同步。
- 监听 `messaging-history.set`、`contacts.upsert/update`、`chats.upsert/update`。
- pure normalizer 过滤 status/broadcast/newsletter/系统 JID；个人 `@s.whatsapp.net`/`@lid` 进入联系人；群 `@g.us` 只进入会话。
- 联系人/聊天每批最多 200，历史消息每批最多 100；事件 ID 由 source/kind/chunk item identity 稳定生成。
- generation 阻止旧 socket 批量事件。
- FastAPI 事务批量 account-scoped upsert，partial update 保留缺失字段；同步不得覆盖 remark/tags/notes/language。
- 历史消息以 `(account_id, wa_message_id)` 幂等，重复不增加 unread，`from_me` 不增加 unread；旧时间不回退会话 preview。
- 消息读取先 SQL 倒序取最近 N 条，再正序返回。

## RED 测试

1. Bridge normalizer/chunker 测试：JID 分类过滤、partial 字段、批大小、稳定 identity。
2. AccountSession 测试：五类 Baileys 批量事件、历史组合事件、generation 防旧 socket。
3. Baileys adapter 源码契约：`syncFullHistory: true` 且允许历史处理。
4. FastAPI 事件测试：五类新事件类型、批量 upsert、人工字段保护、群不建联系人、幂等 unread/preview。
5. Conversation API 测试：数据库最近 N 条、响应升序。

首次 RED 预期原因：新事件类型/Pydantic payload、Bridge normalizer/chunker 和监听器尚不存在，当前消息查询取最早 N 条。
