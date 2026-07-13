# Standalone Runtime Cutover Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Run the WhatsApp console as an independent FastAPI + Bridge V2 + business-database system, with no runtime dependency on Hermes CLI, gateway, profile, or `state.db`.

**Architecture:** The production API receives all runtime paths from `CHAT_SYSTEM_RUNTIME_DIR` and all business data from `DATABASE_URL`. React reads only `/api/v1` standalone APIs. Bridge V2 owns independent Baileys credentials, spool, and media below its own runtime root; it posts events directly to FastAPI. The former Hermes `state.db` is used only by an explicit, read-only import command during migration, never by the serving process.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy/Alembic, SQLite now (PostgreSQL-ready), Node 20 + Baileys Bridge V2, React/Vite, systemd.

**Requirements:** `FR-CORE-001`, `FR-CORE-002`, `FR-ACC-003`, `FR-CON-003`, `MIG-001`, `MIG-002`, `QA-001`.

---

### Task 1: Define independent runtime configuration and deployment contract

**Objective:** Remove profile selection from the service startup contract and explicitly define independent directories, database and internal-event configuration.

**Files:**
- Modify: `docs/sdd/02-system-architecture.md`
- Modify: `docs/sdd/07-migration-and-rollout.md`
- Modify: `docs/sdd/05-optimization-backlog.md`
- Create: `deploy/systemd/whatsapp-bridge-v2.service`
- Modify: `deploy/systemd/whatsapp-chat-system.service`
- Test: `tests/test_cli.py`

**Steps:**
1. Write tests proving `serve` has no `--profile` argument and starts with runtime configuration only.
2. Implement `CHAT_SYSTEM_RUNTIME_DIR` and required independent service environment inputs.
3. Make API and Bridge units use only project/runtime paths and environment files; never `/root/.hermes`.
4. Document the rollback boundary: legacy processes remain stopped only after import and Bridge V2 live readiness.

### Task 2: Make the API runtime independent

**Objective:** Start the API without loading a Hermes profile or constructing the legacy router/state database.

**Files:**
- Modify: `src/whatsapp_chat_system/config.py`
- Modify: `src/whatsapp_chat_system/cli.py`
- Modify: `src/whatsapp_chat_system/web_api.py`
- Create: `src/whatsapp_chat_system/runtime.py`
- Test: `tests/test_standalone_runtime.py`

**Steps:**
1. Write a failing test that builds the standalone app with a temporary runtime directory while `HERMES_HOME` is absent and checks `/api/health` reports standalone mode.
2. Add an explicit runtime mode with standalone as the only production service mode.
3. In standalone mode, do not instantiate `StateDB`, `AdminRouter`, `AdminForwarder`, `MemoryRefresher`, or any Hermes messenger.
4. Disable legacy-only `/api/conversations`, `/api/reply`, `/api/chat/*`, and profile-derived settings routes with a structured migration error rather than silently falling back.
5. Keep the V2 router, independent DB, auth and internal event receiver operational.

### Task 3: Switch React to a single standalone data plane

**Objective:** Remove all Legacy API requests and source branches from the live console.

**Files:**
- Modify: `web/src/App.jsx`
- Modify: `web/src/inboxModel.js`
- Modify: `web/src/conversationLifecycle.js`
- Modify: `web/src/components/ChatPane.jsx` as needed
- Test: `web/tests/standaloneRuntime.test.js`

**Steps:**
1. Write static/behavioral tests asserting workspace load calls only `/v1/conversations` and `/v1/contacts`.
2. Replace merged Legacy/V2 inbox construction with standalone account-scoped conversations.
3. Remove Legacy contact restoration, deletion and `/api/reply` send fallback from UI routing.
4. Keep account isolation, pagination, pin/delete and mobile navigation behavior intact.

### Task 4: Provide a one-time read-only legacy importer

**Objective:** Migrate historical contacts, conversations and messages from an explicitly supplied old SQLite file into one standalone account without runtime reads of Hermes data.

**Files:**
- Create: `src/whatsapp_chat_system/legacy/__init__.py`
- Create: `src/whatsapp_chat_system/legacy/importer.py`
- Modify: `src/whatsapp_chat_system/cli.py`
- Test: `tests/test_legacy_importer.py`

**Steps:**
1. Write fixtures for a minimal legacy SQLite state database and expected import report.
2. Implement `import-legacy --source-db PATH --account-id ID --dry-run` using a read-only SQLite connection.
3. Upsert by `(account_id, remote_jid)` and `(account_id, wa_message_id)`; preserve chronology and report imported/skipped/conflicted counts without exposing source paths in HTTP responses.
4. Require the destination standalone account to exist; do not create one implicitly from external data.
5. Run dry-run, then actual import against a copied read-only snapshot only after schema and account preconditions pass.

### Task 5: Independently deploy and cut traffic to V2

**Objective:** Run only independent API and Bridge services, migrate history, and verify the actual production data plane.

**Files:**
- Modify: `deploy/apply-standalone.sh`
- Modify: `docs/standalone-migration-checklist.md`
- Modify: `docs/CHANGELOG_AGENT.md`
- Modify: `docs/PROJECT_MEMORY.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/TODO_AGENT.md`

**Steps:**
1. Build frontend and run migrations against the independent business database.
2. Install/restart independent `whatsapp-chat-system.service` and `whatsapp-bridge-v2.service`; verify `8792` and `3100` readiness without any Hermes process ownership.
3. Import a snapshot report, then stop `hermes-gateway-whatsapp-support.service` and legacy Bridge only after the standalone listener and DB API are healthy.
4. Verify health, static assets, V2 conversations/contacts, Bridge live/ready, service environment and logs contain no Hermes runtime paths.
5. QR login, real inbound/outbound/receipt validation remains a physical WhatsApp action; until performed, record the cutover as `Implemented`, not `Verified`.
