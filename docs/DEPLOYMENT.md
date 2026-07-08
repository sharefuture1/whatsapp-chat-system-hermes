# Deployment Notes

## Local dev

Backend:

```bash
cd /root/whatsapp-chat-system
./.venv/bin/python -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8792
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

## Production frontend host

Current intended public frontend host:
- `https://whats.future1.us`

## Vercel-ready frontend

Set on Vercel:
- `VITE_API_BASE=https://whats.future1.us/api`

The frontend code supports:
- local dev via `/api`
- production direct API calls via `VITE_API_BASE`

Repo root `vercel.json` is configured to:
- build only `web/`
- publish `web/dist`
- rewrite `/api/*` to `https://whats.future1.us/api/*`
- rewrite all other paths to `/index.html`

## Vercel deployment steps

```bash
cd /root/whatsapp-chat-system
vercel pull --yes
vercel build
vercel deploy --prebuilt
```

If running CI or non-interactive deploys, set:
- `VERCEL_TOKEN`

## Production recommendations

Recommended production shape:
- build frontend with `npm run build`
- deploy frontend to Vercel or serve static assets via Caddy/Nginx
- run backend via systemd on localhost only
- expose backend through a domain/tunnel reachable as `https://whats.future1.us/api`
- keep the tunnel/proxy in front of the single frontend origin

## Security checklist

Before wider use:
- change the bootstrap/default password immediately
- rotate any profile-local API keys if this project or profile files were copied around
- keep login throttling enabled
- keep session TTL enabled
- consider IP allowlisting or tunnel access policy
