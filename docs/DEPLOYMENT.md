# Deployment Notes

## Local development

Backend:

```bash
cd /root/whatsapp-chat-system
./.venv/bin/python -m whatsapp_chat_system.cli \
  --profile /root/.hermes/profiles/whatsapp-support \
  serve --host 127.0.0.1 --port 8792
```

Frontend:

```bash
cd /root/whatsapp-chat-system/web
npm run dev -- --host 127.0.0.1 --port 38998
```

The Vite dev server proxies `/api` to `127.0.0.1:8792`.

## Public host model

Current intended public frontend/backend origin:
- `https://whats.future1.us`

The intended public backend base is:
- `https://whats.future1.us/api`

## Vercel frontend deployment

Set on Vercel:
- `VITE_API_BASE=https://whats.future1.us/api`

The frontend supports two modes:
- local development: use `/api` through Vite proxy
- production/Vercel: use `VITE_API_BASE`

Repo root `vercel.json` is already configured to:
- install/build only `web/`
- publish `web/dist`
- rewrite `/api/*` to `https://whats.future1.us/api/*`
- rewrite all other paths to `/index.html`

That means the Vercel frontend can link to the backend API if and only if:
- `https://whats.future1.us/api/health` is publicly reachable
- the backend proxy/tunnel correctly forwards to the live 8792 backend

## Vercel deployment commands

```bash
cd /root/whatsapp-chat-system
vercel pull --yes
vercel build
vercel deploy --prebuilt
```

For CI or non-interactive deploys, set:
- `VERCEL_TOKEN`

## Recommended production topology

Recommended shape:
- frontend deployed to Vercel
- backend running via systemd on localhost only
- public hostname/tunnel/proxy forwards `/api/*` to backend 8792
- frontend and backend share the same public origin family under `whats.future1.us`

## Multi-channel / multi-account roadmap

The best Hermes-native evolution path is:
- one Hermes profile per channel/account
- one aggregate console frontend/backend

Examples:
- `whatsapp-support-a`
- `whatsapp-support-b`
- `telegram-support-a`
- future `wechat-*` bridge/profile

Console responsibilities:
- unify inbox view
- label platform/account source
- route sends through the correct Hermes profile
- expose health/status per workspace

## Current verified local behavior

Verified:
- backend on 8792
- frontend on 38998
- login works with current password
- paginated conversation loading works
- newest messages anchor at bottom
- auto-translation fields return from API
- frontend production build succeeds

## Security checklist

Before broader rollout:
- rotate API keys if copied around
- change the deployment password if shared
- keep session TTL enabled
- keep login throttling enabled
- consider access policy / IP allowlisting on the public hostname
