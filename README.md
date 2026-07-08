# WhatsApp Chat System

A private operator console for Hermes-based WhatsApp support workspaces.

This project provides:
- a Python backend API built with FastAPI
- a React operator console
- configurable admin delivery channels
- smart / translate / direct reply modes
- per-user memory refresh and operator-side conversation monitoring
- session-protected login for the web console

Current default login password:
- `test?9`

Important note:
- The current Hermes WhatsApp bridge does NOT expose a real revoke/delete-for-everyone API.
- This project therefore supports local admin-console hide/delete only, not bilateral WhatsApp deletion.

## Features

- Secure web login with password-based session token
- Dashboard metrics for active conversations and admin delivery channels
- Conversation browser with memory summary
- Reply composer with:
  - direct send
  - smart rewrite
  - translate-first
  - preview before send
- Configurable reply policy from the UI:
  - default mode
  - smart max length
  - translate max length
  - preview debounce
  - fallback control
- Configurable admin channel routing:
  - WhatsApp
  - Telegram
  - WeChat / Weixin placeholders
- Quick local hide for messages in the admin console
- Bulk local hide for latest N messages in a thread

## Repository layout

```text
src/whatsapp_chat_system/
  cli.py               CLI entrypoints
  web_api.py           FastAPI API
  config.py            profile-aware config + web settings + password record
  router.py            admin routing logic
  rewriter.py          smart / translate rewrite logic
  forwarder.py         assistant/user transcript forwarding to admins
  memory_refresh.py    markdown profile generation from Hermes state.db
  messaging.py         Hermes send wrapper + target resolution
  storage.py           DB access helpers + event logger
  parsing.py           admin command parsing
  language.py          language and tone heuristics
  profile.py           user profile synthesis

web/
  src/App.jsx          React console
  src/styles.css       console styling
  package.json         frontend dependencies
  vite.config.js       dev server config + /api proxy

tests/
  pytest coverage for API and core parsing/rewrite flows
```

## Requirements

- Python 3.11+
- Node.js 20+
- npm 10+
- A Hermes profile already configured for WhatsApp
- A valid Hermes CLI installed on the machine

## Quick start

### 1. Create the Python venv and install backend deps

```bash
cd /root/whatsapp-chat-system
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
pip install pytest fastapi uvicorn pydantic requests pyyaml httpx2
```

### 2. Install frontend deps

```bash
cd /root/whatsapp-chat-system/web
npm install
```

### 3. Run the backend

```bash
cd /root/whatsapp-chat-system
./.venv/bin/python -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8791
```

### 4. Run the frontend

Example fixed port setup:

```bash
cd /root/whatsapp-chat-system/web
npm run dev -- --host 127.0.0.1 --port 38998
```

Then open:
- `http://127.0.0.1:38998/`

## Authentication

The web console uses password login.

Default configured password:
- `test?9`

Login endpoint:
- `POST /api/login`

On successful login the frontend stores a session token and sends it in:
- `x-session-token`

Protected endpoints reject unauthenticated access with HTTP 401.

## Configuration files

Profile-local files used by this project:

- `admin-channels.json`
  - operator delivery channels
- `web-settings.json`
  - UI/reply/auth settings
- `user-aliases.json`
  - numeric aliases for contacts
- `user-memory-md/`
  - generated per-user markdown summaries
- `.admin-command-router-state.json`
- `.admin-forward-state.json`

## API overview

### Public
- `GET /api/health`
- `POST /api/login`

### Authenticated
- `GET /api/dashboard`
- `GET /api/conversations`
- `GET /api/conversations/{user_id}`
- `POST /api/reply`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/messages/hide`
- `POST /api/jobs/run`

## Reply modes

### direct
Sends the operator text as-is.

### smart
Uses user memory + language/tone heuristics + model rewrite.

### translate
Translates toward the detected/preferred user language when appropriate.
If the language is unknown, it keeps the original text instead of forcing a wrong translation.

## Message deletion / hiding

What is supported now:
- local admin-console hide of specific messages
- local admin-console hide of latest N messages

What is NOT supported now:
- true WhatsApp bilateral delete / revoke for everyone
- bulk remote deletion from the bridge

Reason:
- the current Hermes WhatsApp bridge exposes send/edit/media/typing/chat/health, but no delete/revoke endpoint

## Testing

Backend tests:

```bash
cd /root/whatsapp-chat-system
./.venv/bin/pytest -q
```

Frontend build verification:

```bash
cd /root/whatsapp-chat-system/web
npm run build
```

## Security notes

Before uploading to a private repository, review and rotate any real secrets in profile-local config files.

Do NOT commit:
- `.venv/`
- `web/node_modules/`
- `web/dist/`
- local databases
- profile-local secrets or API keys

Recommended next security improvements:
- session expiration
- token invalidation on logout
- rate limiting on login
- stronger password bootstrap flow

## Preparing a private GitHub repo

Suggested steps:

```bash
cd /root/whatsapp-chat-system
git init
git add .
git commit -m "feat: initial private operator console"
```

Then create a private repository with `gh`:

```bash
gh repo create <new-private-repo-name> --private --source . --push
```

If `gh` is not authenticated yet:

```bash
gh auth login
```

## Current status

Validated locally:
- backend tests passing
- frontend production build passing
- secure login working
- authenticated settings access working
- preview/send split working
- fixed-port frontend working via local proxy
