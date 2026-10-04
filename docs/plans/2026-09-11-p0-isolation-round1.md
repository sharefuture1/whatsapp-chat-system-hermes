# Round 1 P0 implementation plan

Base: codex/p0-hardening-tauri2. See ../sdd/12-session-translation-isolation.md.

1. RED tests: pending browser cache writes after logout/delete/scope changes;
   stale HTTP responses after session and mutation changes; forced-password API
   restriction; account-scoped translation memory, exact hashes, persistent reuse.
2. Minimal implementation in chatCache.js, api.js, App.jsx, auth API, translation
   enqueue/dispatcher and batch endpoint. Keep existing architecture and defaults.
3. GREEN: Python, Web, Bridge; Browser/Tauri builds and CI format checks.
4. Sync documentation and target branch only after gate verification.
5. gcptw deployment requires a usable server connection and release verification.
   Current conversation open_workspace is denied (developer MCP unsupported).
   No server modification and no six-hour autonomous task have been performed.

## Executed code verification

Steps 1–3 passed in the locked GitHub runner: Python 384 passed / 7 skipped,
Web 138 passed, Bridge 87 passed; Browser/Tauri frontend builds, Ruff and real
Chromium mandatory-password flows at phone and desktop viewports passed.
See [authoritative verification record](../reports/2026-09-11-round1-verification.md)
for exact run, scope, dependency warnings and production limitations.
