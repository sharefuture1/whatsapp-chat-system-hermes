# Round 2：翻译单入口与 Worker 原子重试实施计划

规格：`docs/sdd/13-translation-ingress-and-retry.md`。基线：目标分支最新 `474dc0ba`。

1. RED：策略三种阻断、Standalone 前端双入口、CAS 领取、迟到写回、retry_after 与 max attempts。
2. GREEN：统一 `translation_policy`，入站路由注入策略；Standalone ChatPane 删除自动批次创建。
3. GREEN：Dispatcher 改 CAS claim + claim_attempt 写回保护 + pending/retry_after/dead 状态机。
4. REFACTOR：设置 API 复用同一策略解析，保留 Legacy/手动翻译兼容。
5. 全量：pytest、Web、Bridge、Ruff、Browser/Tauri build。
6. 通过后更新项目四文件并合并 `codex/p0-hardening-tauri2`；gcptw 只有在服务器连接真实可用时另行部署验证。
