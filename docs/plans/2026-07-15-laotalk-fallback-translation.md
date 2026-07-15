# 2026-07-15 LaoTalk fallback translation integration plan

## Goal
在 WhatsApp Chat System 中把 LaoTalk API 接入为消息翻译的备选 provider，并在 AI 翻译失败时自动回退到 LaoTalk，且可在系统设置中选择/查看翻译 provider。

## Scope
- 后端消息翻译链路（单条 + batch dispatcher）
- 运行时设置与系统设置 API
- 前端 SettingsPage 聊天/翻译设置
- 基础稳定性修复：SQLite 锁竞争与前端翻译节流

## Non-goals
- 不替换 reply/smart rewrite 主 AI provider
- 不把 LaoTalk 用于 persona/rewrite/auto-reply 主模型

## Requirements mapping
- SDD-P0-01 独立 AI/Provider 配置
- SDD-P1-05 翻译数据库真源
- SDD-P1-11 设置二级页
- FR-AI / API / UX 相关翻译设置扩展

## Steps
1. 扩展 runtime 默认 `message_ops`：新增 `translation_provider` 和 `translation_fallback_provider`
2. 后端实现 LaoTalk translate client（HTTP GET /api/translate）
3. Rewriter.translate_to_zh_result 增加 provider/fallback provider 参数或从 web_settings 读取
4. 单条翻译 API / batch dispatcher 统一走新 provider 选择逻辑
5. `/api/v1/settings` 与 `/api/v1/ai/settings` 返回 provider 相关可见状态
6. 前端 SettingsPage chat 子页新增 provider/fallback 选择
7. 构建、真实 curl、服务重启、消息接口验证
8. 更新 SDD / PROJECT_MEMORY / TODO / CHANGELOG
