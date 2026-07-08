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

## Vercel-ready frontend

The frontend should be deployable independently and talk to a remote backend.

Recommended pattern:
- keep FastAPI backend running on your Hermes host
- expose backend publicly through a stable domain or tunnel
- configure the frontend to call that backend directly in production

Suggested production env var for the web app:
- `VITE_API_BASE=https://your-backend-host/api`

Then the frontend should use that base URL instead of assuming local `/api`.

## Vercel

The repo root `vercel.json` builds only the React console (`web/`) and serves
it as a static site. The Vercel GitHub integration deploys `main` to
production and every branch push to a preview URL.

To make a Vercel deployment fully functional, the backend must already be
reachable from the public internet. The frontend cannot use the local Hermes
profile directly.

## Production recommendations

Do not use Vite dev server forever.

Recommended production shape:
- build frontend with `npm run build`
- serve static assets via Caddy or Nginx, or deploy the frontend to Vercel
- run backend via systemd on localhost only
- reverse proxy `/api` to backend, or configure `VITE_API_BASE`
- put the tunnel or HTTPS gateway in front of the single frontend origin

## Security checklist

Before wider use:
- change the default bootstrap password immediately
- rotate any profile-local API keys if this project or profile files were copied around
- keep login throttling enabled
- keep session TTL enabled
- consider IP allowlisting or tunnel access policy
