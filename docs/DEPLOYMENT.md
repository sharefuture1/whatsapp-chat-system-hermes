# Deployment Notes

## Local dev

Backend:

```bash
cd /root/whatsapp-chat-system
./.venv/bin/python -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8791
```

Frontend (fixed port example):

```bash
cd /root/whatsapp-chat-system/web
npm run dev -- --host 127.0.0.1 --port 38998
```

## Tunnel target

When using a single frontend entrypoint, expose:
- `http://127.0.0.1:38998`

The Vite dev server proxies `/api` to the backend.

## Vercel (static frontend preview)

The repo root `vercel.json` builds only the React console (`web/`) and serves
it as a static site. The Vercel GitHub integration deploys `main` to
production and every branch push to a preview URL.

Current limitations on Vercel:
- The FastAPI backend can NOT run on Vercel: it reads the local Hermes
  profile (`state.db`, profile-local JSON files) and shells out to the
  `hermes` CLI, so it must run on the machine that hosts the Hermes profile.
- `/api/*` is excluded from the SPA rewrite, so API calls return 404 until a
  backend rewrite is added. The console loads up to the login screen only.

To make a Vercel deployment fully functional, expose the backend publicly
(e.g. a Cloudflare tunnel in front of `127.0.0.1:8791`) and add a rewrite
BEFORE the SPA fallback in `vercel.json`:

```json
{ "source": "/api/(.*)", "destination": "https://<your-backend-host>/api/$1" }
```

Do this only after the P0 security items in `docs/SDD.md` are fixed
(password KDF, token expiry, login throttling, fail-closed auth).

## Production recommendations

Do not use Vite dev server forever.

Recommended production shape:
- build frontend with `npm run build`
- serve static assets via Caddy or Nginx
- run backend via systemd on localhost only
- reverse proxy `/api` to backend
- put the tunnel in front of the single frontend origin

## Security checklist

Before wider use:
- change the default password
- rotate any profile-local API keys if this project or profile files were copied around
- add session expiry
- add login throttling
- consider IP allowlisting or tunnel access policy
