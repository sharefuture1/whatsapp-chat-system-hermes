# Hermes Messaging Operations Console

A private multi-channel operator console for Hermes-based messaging workspaces.

This project now acts as a conversation-first control surface for Hermes profiles and messaging channels, with a WeChat-style UI direction and a FastAPI backend.

## What it does

- secure web login with session-based auth
- WeChat-style operator inbox UI
- reply composer with:
  - direct send
  - smart rewrite
  - translate-first
  - preview before send
- automatic in-thread message translation to Chinese
- local console hide/delete of messages
- conversation memory generation
- configurable admin delivery channels
- Vercel-ready frontend that can call a remote backend API
- Tauri 2 thin-client shell for Windows, macOS, Linux, Android, and iOS
- self-hosted production mode with built SPA mounted by FastAPI or served by nginx

## Current UI model

The frontend is now structured like a WeChat-style shell with 4 tabs:
- Chats
- Contacts
- Discover
- Me

Design principles:
- chat is the primary workspace
- settings should not interrupt normal messaging
- old messages should load on demand only
- newest messages should stay anchored at the bottom
- mobile and desktop should both be first-class experiences

## Runtime secrets policy

Do not store live passwords or API secrets in this repository.
Current runtime auth state always lives in the target Hermes profile, typically:
- `/root/.hermes/profiles/whatsapp-support/web-settings.json`

If bootstrapping a fresh deployment, prefer runtime env override:
- `CHAT_SYSTEM_BOOTSTRAP_PASSWORD=...`

## Important limitations

The current Hermes WhatsApp bridge does NOT expose true revoke/delete-for-everyone.
So this project supports:
- local admin-console hide
- local bulk hide

It does NOT support:
- bilateral WhatsApp revoke/delete-for-everyone

## Repository layout

```text
src/whatsapp_chat_system/
  cli.py                    CLI entrypoints
  web_api.py                FastAPI API (+ optional built SPA mount)
  config.py                 profile-aware config + merged defaults + auth settings
  router.py                 admin routing logic
  rewriter.py               smart / translate / auto-translation logic
  forwarder.py              transcript forwarding to admins
  memory_refresh.py         markdown + structured sidecar generation
  messaging.py              Hermes send wrapper + target resolution
  storage.py                DB access helpers
  origins.py                sessions.json cache
  structured_profile.py     structured profile sidecar
  translations.py           per-user translation cache
  parsing.py                admin command parsing
  language.py               heuristics + low-info handling
  profile.py                user profile synthesis

web/src/
  App.jsx                   frontend shell
  api.js                    API client
  i18n.js                   translation strings
  settings.jsx              theme/language provider
  styles.css                WeChat-style UI stylesheet
  components/
    ChatList.jsx
    ChatPane.jsx
    ContactsPage.jsx
    DiscoverPage.jsx
    LoginScreen.jsx
    MePage.jsx
    SettingsPanel.jsx
    TabBar.jsx

src-tauri/
  tauri.conf.json           desktop/mobile shell and CSP
  capabilities/main.json   least-privilege remote API access
  src/                      Rust entrypoints

deploy/
  apply-production.sh       blocked legacy helper
  nginx/                    sample reverse-proxy config
  systemd/                  production unit file

tests/
  conftest.py               isolated profile fixtures
  test_web_api.py
  test_origins.py
  test_structured_profile.py
  test_pagination.py
  test_search.py
  test_translation.py
  test_i18n_consistency.py
```

## Local development

### Backend

```bash
export DATABASE_URL='postgresql+psycopg://...'
export WHATSAPP_BRIDGE_INTERNAL_TOKEN='set-in-your-local-secret-store'
export CHAT_SYSTEM_BOOTSTRAP_PASSWORD='at-least-12-characters'
uv sync --locked --group dev
uv run whatsapp-chat-system serve --host 127.0.0.1 --port 8792
```

### Frontend

```bash
npm ci --prefix web
npm run dev --prefix web
```

Open:
- `http://127.0.0.1:38998/`

## Production deployment

Frontend must be built before production startup. The supported standalone
installation path is `/opt/whatsapp-chat-system`:

```bash
cd /opt/whatsapp-chat-system
npm ci --prefix web
npm run build --prefix web
```

Run the API with deployment secrets supplied by
`/etc/whatsapp-chat-system/api.env` (or an equivalent secret store):

```bash
/opt/whatsapp-chat-system/.venv/bin/python -m whatsapp_chat_system.cli \
  serve --host 127.0.0.1 --port 8792 \
  --web-dist /opt/whatsapp-chat-system/web/dist
```

The reviewed service definitions are in `deploy/systemd/`; nginx serves the
same `web/dist` path from `deploy/nginx/whats.future1.us.conf`. The historical
`deploy/apply-production.sh` is intentionally blocked and must not be used for
the standalone cutover.

This production path removes dependence on:
- `npm run dev`
- `vite preview`
- ad-hoc Python static servers

## Authentication model

Login endpoint:
- `POST /api/login`

On successful login, the frontend stores a session token and sends:
- `x-session-token`

Current auth features:
- PBKDF2-HMAC-SHA256 password hash
- session TTL
- server-side logout invalidation
- login throttling

## API overview

### Public
- `GET /api/health`
- `POST /api/login`

### Authenticated
- `POST /api/logout`
- `GET /api/dashboard`
- `GET /api/conversations?page=&page_size=`
- `GET /api/conversations/{user_id}?page=&page_size=`
- `GET /api/search?q=`
- `POST /api/reply`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/messages/hide`
- `POST /api/messages/{message_id}/translate`
- `POST /api/jobs/run`

## Translation behavior

Auto-translation is now designed for chat readability, not literal academic translation.

It supports:
- per-message Chinese translation shown below non-Chinese messages
- deterministic handling for low-information Lao/Thai fillers
- cached translation results per user
- settings toggle in the UI

Examples:
- `ໂດຍ` -> `嗯`
- `โอเค` -> `好的`

## Multi-channel direction

The current codebase is evolving from a single-workspace WhatsApp console into a multi-channel operator console.

Current support in the codebase:
- conversations are no longer hard-filtered to WhatsApp only
- Telegram display names get `-tg` suffix in summaries/details/search
- admin delivery channels are configurable

Recommended production architecture:
- one Hermes profile per channel/account
  - e.g. `whatsapp-support-a`
  - `whatsapp-support-b`
  - `telegram-support-a`
- one aggregate operations console
- route outbound messages by workspace/profile
- display platform and account identity in the UI

## Vercel deployment

The frontend is designed to deploy independently to Vercel and call the backend over HTTPS.

Production frontend host:
- `https://whats.future1.us`

Frontend production API base:
- browser build: same-origin `/api`
- packaged Tauri build: `https://whats.future1.us/api`

Repo root `vercel.json` is configured to:
- build only `web/`
- publish `web/dist`
- rewrite `/api/*` to `https://whats.future1.us/api/*`
- rewrite all other paths to `/index.html`

That means the deployed frontend should still reach the backend API as long as:
- `https://whats.future1.us/api/...` is reachable from the public internet
- the backend is running on the host and proxied correctly

## Tauri 2 desktop and mobile shell

The packaged application is intentionally a thin client: React/Vite runs in
Tauri while the FastAPI service, PostgreSQL database, and WhatsApp Bridge remain
on the server. This keeps Windows, macOS, Linux, Android, iOS, and the browser on
one API contract without placing database or Bridge credentials on end-user
devices.

```bash
npm ci
npm ci --prefix web
npm run tauri:dev
npm run tauri:build

# Native projects require the Android/iOS prerequisites first.
npm run tauri:android:init
npm run tauri:ios:init       # macOS only
```

See `docs/TAURI2.md` for platform prerequisites, scoped HTTP permissions,
signing/update policy, mobile UX requirements, and store-readiness gates.

## Testing

Backend tests:

```bash
uv run --group dev pytest -q
```

Frontend build verification:

```bash
npm ci --prefix web
npm run build --prefix web
npm run web:build:tauri
```

Runtime verification:

```bash
curl -fsS http://127.0.0.1:8792/api/health
curl -I http://127.0.0.1:8792/
curl -fsS http://127.0.0.1:8792/chats/123 | head
```

## Security notes

Before wider use:
- rotate profile-local API keys separately from repo changes
- keep login/bootstrap secrets out of git
- keep login throttling and session TTL enabled
- consider IP allowlisting / tunnel access policy
- keep backend bound to localhost behind reverse proxy / tunnel

## Status

Validated in mirror workspace:
- backend tests passing
- frontend production build passing
- secure login working
- session logout working
- paginated conversations and message history
- automatic translation cache
- WeChat-style shell with 4 tabs
- Vercel-ready frontend API linkage
- built frontend can now be served from FastAPI root in production mode
