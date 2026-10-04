# WhatsApp Chat System

A self-hosted, multi-account WhatsApp operations console: conversation-first
inbox, automatic in-thread translation, and AI-assisted replies — with a
FastAPI backend, a React SPA, a Tauri 2 thin client, and a Node/Baileys bridge.

The backend runs standalone from its own database and runtime directory. It does
**not** require any external profile, gateway, or legacy runtime to start.

## Capabilities

- Multi-account WhatsApp send/receive with per-account isolation (Baileys bridge)
- WeChat-style operator console: Chats / Contacts / Discover / Me
- Reply composer: direct send, smart rewrite, translate-first, preview before send
- Automatic in-thread translation to Chinese, with a self-learning phrase memory
- AI-assisted replies driven by a configurable model profile
- Relationship intelligence: conversation summaries, long-term memory, contact profiles
- Transactional outbox for outbound messages (lease + backoff + idempotency key)
- Session-based web login, PBKDF2 password hashing, login throttling
- Trilingual UI (zh / en / th) with light and dark themes
- Tauri 2 desktop shell for Windows / macOS / Linux

## Architecture

| Layer | Implementation |
| :--- | :--- |
| Control API | FastAPI + SQLAlchemy 2.0 (sync) + Alembic, entrypoint `standalone_api.py` |
| Background work | In-process coroutine loops driven from the FastAPI lifespan (account reconciler, outbox, auto-reply, auto-reply reconciler, translation dispatcher) |
| Store | **SQLite or PostgreSQL** — same code path, `DATABASE_URL` switchable |
| WhatsApp bridge | `bridge/` — Node 20 + Baileys 6.7.22, per-account event spool |
| Frontend | `web/` — Vite 5 + React 18 (plain JS/JSX), no SSR, no router |
| Desktop | `src-tauri/` — Tauri 2 thin client, least-privilege remote API scope |

Design notes that matter for operations:

- The outbox worker claims work with a **conditional UPDATE (CAS)**, not
  `SELECT ... FOR UPDATE`. SQLite silently ignores row locks, which previously
  allowed two workers to claim and send the same message twice.
- The translation dispatcher follows
  **short transaction → AI call with no open session → short transaction**.
  Network I/O never happens while a database transaction is held.
- The internal event endpoint authenticates with a shared token and, when
  `WHATSAPP_BRIDGE_HMAC_SECRET` is set, an additional HMAC-SHA256 signature over
  the raw body plus a timestamp window and nonce replay guard.

## Repository layout

```text
src/whatsapp_chat_system/
  cli.py                       CLI entrypoints (`serve`)
  standalone_api.py            FastAPI application factory
  runtime.py                   runtime directory + persisted settings
  settings.py                  DatabaseSettings / AISettings
  outbox.py                    transactional outbound queue
  translations_dispatcher.py   translation batch scheduler
  translation_memory.py        self-learning phrase memory
  rewriter.py                  smart / translate logic
  api/v1/                      REST routers (accounts, conversations, messages,
                               settings, operations, personas, plugins, users)
  api/internal/whatsapp_events.py
                               bridge event ingestion endpoint
  ai/                          provider, service, auto-reply worker, crypto
  accounts/                    account reconciliation + repository
  db/                          models, session, url normalization
  events/whatsapp.py           event ingestion service
  security/internal_auth.py    token + HMAC verification

bridge/src/                    Node/Baileys bridge (events/, file spool, server)

web/src/                       React SPA (api.js, i18n.js, components/)

src-tauri/                     Tauri 2 shell and capability scope

deploy/
  systemd/                     API units (single-process and API-only) + bridge unit
  nginx/                       sample reverse-proxy config

scripts/
  run_server.py                cross-platform launcher (Linux/macOS/Windows)

tests/                         pytest suite (incl. opt-in PostgreSQL suite)
docs/                          deployment, architecture, SDD specifications
```

## Local development

### Backend

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .

cp .env.example .env      # set WHATSAPP_BRIDGE_INTERNAL_TOKEN at minimum
alembic upgrade head      # schema migration is an explicit prerequisite
python scripts/run_server.py --check     # config self-check, starts nothing
python scripts/run_server.py             # pure API mode
```

`scripts/run_server.py` loads `.env`, derives a runtime directory and a default
SQLite path, and validates the configuration before starting. It works
identically on Linux, macOS, and Windows.

Prefer the CLI directly if you already export the environment:

```bash
python -m whatsapp_chat_system.cli serve --host 127.0.0.1 --port 8792
```

### Frontend

```bash
npm ci --prefix web
npm run dev --prefix web
```

## Configuration

`.env.example` is the full reference. The required minimum:

| Variable | Purpose |
| :--- | :--- |
| `WHATSAPP_BRIDGE_INTERNAL_TOKEN` | Shared token for the bridge → API event endpoint |
| `DATABASE_URL` | `sqlite:////abs/path/app.db` or `postgresql://...` |
| `CHAT_SYSTEM_BOOTSTRAP_PASSWORD` | First boot only; ≥12 chars, initialises runtime settings |

Strongly recommended in production: `WHATSAPP_BRIDGE_HMAC_SECRET`,
`AI_SECRET_ENCRYPTION_KEY`, `CHAT_SYSTEM_ALLOWED_ORIGINS`.

## Testing

```bash
pytest -q                     # backend
npm run web:test              # frontend (node:test)
npm run bridge:test           # bridge (node:test)
npm test                      # frontend + bridge
```

PostgreSQL behaviour is covered by an opt-in suite that requires a disposable
database — **it truncates the tables it uses**:

```bash
TEST_DATABASE_URL='postgresql://user:pass@host:5432/whatsapp_test' \
  pytest tests/test_postgres_backend.py -v
```

It verifies migration DDL, foreign-key enforcement, event idempotency, outbox
CAS claiming, row-lock availability, and case-insensitive search.

## Deployment

Full instructions: **[`docs/STANDALONE-DEPLOYMENT.md`](docs/STANDALONE-DEPLOYMENT.md)**.

Two supported shapes:

- **Split deployment (recommended)** — the API runs as a pure API; the SPA is
  hosted separately (Vercel / Nginx / object storage). Set
  `VITE_API_BASE_URL=https://<api-host>/api` at build time and add the frontend
  origin to `CHAT_SYSTEM_ALLOWED_ORIGINS`.
- **Single process** — pass `--web-dist web/dist` and the API also serves the
  built SPA.

Platform notes: `deploy/systemd/` for Linux,
`deploy/systemd/whatsapp-chat-system-api-only.service` for an API-only unit,
and `scripts/run_server.py` for Windows and macOS.

## Frontend API base

| Value | Result |
| :--- | :--- |
| `VITE_API_BASE_URL=https://api.example.com/api` | Browser calls that absolute API origin (SDD VCL-002, the authoritative mode) |
| unset | Falls back to the relative path `/api`, requiring a same-origin proxy or single-process mode |
| `VITE_API_BASE` (legacy name) | Still honoured for backward compatibility, logs a deprecation warning |

`VITE_*` values are **public** — they are embedded in the shipped bundle. Never
put tokens, passwords, or keys in a Vite variable.

## Security model

- Keep the API bound to localhost behind a reverse proxy or tunnel.
- Keep `CHAT_SYSTEM_ALLOWED_ORIGINS` explicit; wildcards are rejected because the
  console carries an operator session token.
- Set and back up `AI_SECRET_ENCRYPTION_KEY`. AI API keys are encrypted at rest
  with Fernet; losing the master key makes stored ciphertext unrecoverable.
- Enable `WHATSAPP_BRIDGE_HMAC_SECRET` on both the API and the bridge. Enabling
  it on one side only will cause every event to be rejected.
- Rotate secrets outside of repository changes, and never commit them.

See `docs/STANDALONE-DEPLOYMENT.md` for the verification checklist (config
self-check, health probe, unauthenticated-request probe, CORS probe).

## API overview

Public: `GET /api/health`, `POST /api/login`

Authenticated (session token via `x-session-token`): conversations, messages,
search, reply, settings, accounts, personas, plugins, operations.

Internal (bridge only, `/internal/events/whatsapp`): HMAC-signed event ingestion.

## Translation behaviour

Translation targets chat readability rather than literal accuracy: it preserves
tone and emoji, never merges messages, short-circuits messages already in
Chinese, and learns from operator corrections through the phrase memory. Known
low-information Lao/Thai fillers are resolved deterministically (for example
`ໂດຍ` → `嗯`, `โอเค` → `好的`).

## Documentation

| Document | Contents |
| :--- | :--- |
| [`docs/STANDALONE-DEPLOYMENT.md`](docs/STANDALONE-DEPLOYMENT.md) | Deployment guide: platforms, split vs single-process, signing, checklist |
| [`docs/sdd/README.md`](docs/sdd/README.md) | Authoritative specification index (requirements, architecture, data model, API, performance, workflow) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Architecture and decoupling scope |
| [`docs/ARCHITECTURE_OPTIMIZATION.md`](docs/ARCHITECTURE_OPTIMIZATION.md) | Optimization blueprint and risk matrix |
| [`AGENTS.md`](AGENTS.md) | Mandatory workflow for agent-assisted changes |
| [`docs/TAURI2.md`](docs/TAURI2.md) | Desktop shell security model and build gates |
| [`docs/CHANGELOG_AGENT.md`](docs/CHANGELOG_AGENT.md) | Chronological change log |
| [`docs/PROJECT_MEMORY.md`](docs/PROJECT_MEMORY.md) | Current operational state and known issues |
| [`docs/TODO_AGENT.md`](docs/TODO_AGENT.md) | Current execution view |

## Legacy scope

`docs/DEPLOYMENT.md`, `deploy/apply-production.sh`, and the `web_api.py` module
belong to the previous profile-bound runtime. They are retained for rollback and
diagnostic work only and must not be used to start the standalone service.
`deploy/apply-production.sh` exits with code 64 by design.
