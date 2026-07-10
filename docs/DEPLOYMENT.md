# Deployment Notes

## Goal

Productionize the Hermes Messaging Operations Console so production no longer depends on Vite dev runtime or ad-hoc preview/static servers.

Target production shape:
- build frontend once with `npm --prefix web run build`
- serve `web/dist` as static SPA
- keep FastAPI backend on localhost only
- expose public traffic through a real reverse proxy / tunnel
- optionally let FastAPI mount the built SPA directly at `/`

## Local development

Backend:

```bash
cd /root/whatsapp-chat-system
./.venv/bin/python -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8792
```

Frontend dev only:

```bash
cd /root/whatsapp-chat-system/web
npm run dev -- --host 127.0.0.1 --port 38998
```

The Vite dev server proxies `/api` to `127.0.0.1:8792`.
Do not use this mode as the production serving path.

## Production options

### Option A: single FastAPI process serves API + built SPA

After building `web/dist`, start backend with the built frontend mounted:

```bash
cd /var/www/whatsapp-chat-system
npm --prefix web ci
npm --prefix web run build
CHAT_SYSTEM_WEB_DIST=/var/www/whatsapp-chat-system/web/dist \
/var/www/whatsapp-chat-system/.venv/bin/python -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8792 --web-dist /var/www/whatsapp-chat-system/web/dist
```

What this now does:
- `/api/*` stays on FastAPI
- `/` and SPA routes such as `/chats/123` resolve to `web/dist/index.html`
- no Vite runtime is required in production

### Option B: Nginx/Caddy serves static SPA, proxies `/api` to FastAPI

Use the provided sample config under `deploy/nginx/whats.future1.us.conf`.
Recommended when you want the web server to own static file delivery and TLS.

## Systemd production recommendation

Install the provided unit file:

```bash
cd /var/www/whatsapp-chat-system
sudo install -D -m 0644 deploy/systemd/whatsapp-chat-system.service /etc/systemd/system/whatsapp-chat-system.service
sudo systemctl daemon-reload
sudo systemctl enable --now whatsapp-chat-system.service
sudo systemctl restart whatsapp-chat-system.service
```

The unit:
- runs backend from the project virtualenv
- binds only `127.0.0.1:8792`
- mounts `/var/www/whatsapp-chat-system/web/dist`
- avoids any transient `npm run dev` / `vite preview` dependency

## End-to-end apply commands

A ready helper script is included:

```bash
cd /var/www/whatsapp-chat-system
bash deploy/apply-production.sh
```

The script will:
1. build frontend with `npm --prefix web ci && npm --prefix web run build`
2. install/update the systemd unit
3. restart the backend service
4. verify `http://127.0.0.1:8792/api/health`

## Public host model

Current intended public frontend/backend origin:
- `https://whats.future1.us`

Intended public backend base:
- `https://whats.future1.us/api`

For Cloudflare Tunnel / reverse proxy deployment:
- public traffic should terminate at Nginx/Caddy/tunnel edge
- backend remains localhost-only
- never expose Vite dev server publicly as the production path

## Vercel frontend deployment

Set on Vercel:
- `VITE_API_BASE=https://whats.future1.us/api`

Repo root `vercel.json` is configured to:
- install/build only `web/`
- publish `web/dist`
- rewrite `/api/*` to `https://whats.future1.us/api/*`
- rewrite all other paths to `/index.html`

Vercel remains valid for frontend-only deployment, but mirror P0 productionization now also supports a non-Vercel self-hosted SPA path.

## Verification commands

Backend tests:

```bash
cd /root/whatsapp-chat-system
./.venv/bin/pytest -q
```

Frontend build verification:

```bash
cd /root/whatsapp-chat-system
npm --prefix web ci
npm --prefix web run build
```

Runtime health verification:

```bash
curl -fsS http://127.0.0.1:8792/api/health
curl -I http://127.0.0.1:8792/
```

If using mounted SPA mode, also verify a deep route:

```bash
curl -fsS http://127.0.0.1:8792/chats/123 | head
```

## Current verified local behavior in mirror

Validated in the mirror workspace:
- backend test suite passes after adding SPA root mounting tests
- frontend production build succeeds with static output in `web/dist`
- FastAPI can now optionally mount the built frontend directory at `/`
- CLI now exposes `--web-dist` for explicit production startup
- provided systemd/nginx deployment assets remove dependency on Vite dev runtime

## Security checklist

Before broader rollout:
- keep login secrets only in runtime config / env, not repo docs
- keep backend on localhost only
- keep session TTL enabled
- keep login throttling enabled
- place access policy at Cloudflare / reverse proxy if needed
