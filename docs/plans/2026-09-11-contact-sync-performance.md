# 2026-09-11 WhatsApp 联系人/消息同步与性能优化

## Objective

修复生产中联系人名称被空同步覆盖、历史 pushName 未回填、头像未进入会话 API/前端，以及历史消息全局顺序截断导致部分会话同步不完整的问题；同时避免头像补拉阻塞消息主链路。

## Requirement IDs

- FR-CON-011 / FR-CON-013：联系人、会话与 WhatsApp 同步真值
- FR-MSG-002 / FR-MSG-007：消息同步与聊天刷新
- NFR-PERF-001 / NFR-PERF-002：分页、增量与同步性能
- NFR-REL-001 / NFR-REL-002：可靠同步、外部请求有界
- PERF-002 / PERF-008：前端刷新与渲染稳定

## RED

1. Bridge normalizer：缺失的 name/title/avatar 字段不得输出 `null` 并覆盖数据库已有真值；补充 camelCase/常见 Baileys 名称字段。
2. Backend ingest：历史消息 pushName 只能填补空/占位名，不能覆盖已有联系人真名；会话 API 返回 `avatar_url`。
3. Frontend：聊天列表/聊天头部/入站气泡优先渲染真实头像，加载失败回退 initials。
4. History：全局上限不再按输入顺序提前 break，改为每会话有界后按最近时间选择全局 2000 条。
5. Avatar：Bridge 使用独立后台队列调用 `profilePictureUrl`，带 TTL/并发限制，不阻塞 `eventWork`。

## GREEN

- 最小实现上述规则。
- avatar enrichment 仅发 `contacts.update`，不把头像网络 IO 放入消息主串行队列。
- 历史 pushName 只补缺失数据，人工 remark 永不被同步覆盖。

## Gates

- Bridge focused + full tests + lint
- Python focused ingest/API tests + full relevant suite
- Web focused + full tests + build
- Ruff / git diff --check / secret scan
- 生产部署后验证 API/Bridge health、spool 无积压、会话 API 返回 avatar/name 字段、页面 bundle 更新
