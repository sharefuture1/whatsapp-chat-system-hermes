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
