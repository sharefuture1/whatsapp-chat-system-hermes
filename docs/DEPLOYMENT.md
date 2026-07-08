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

The frontend supports a production API base via environment variable.

Set on Vercel:
- `VITE_API_BASE=https://whats.future1.us/api`

Behavior:
- local dev: falls back to `/api`
- Vercel production: calls `VITE_API_BASE`

## Vercel

The repo root `vercel.json` builds only the React console (`web/`) and serves
it as a static site. The Vercel GitHub integration deploys `main` to
production and every branch push to a preview URL.

To make a Vercel deployment fully functional, the backend must already be
reachable from the public internet. The frontend cannot use the local Hermes
profile directly.

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
