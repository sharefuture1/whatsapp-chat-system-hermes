#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=${1:-/var/www/whatsapp-chat-system}
PROFILE_PATH=${2:-/root/.hermes/profiles/whatsapp-support}
BACKEND_PORT=${BACKEND_PORT:-8792}

cd "$REPO_ROOT"

if [ ! -x .venv/bin/python ]; then
  echo "missing virtualenv: $REPO_ROOT/.venv/bin/python" >&2
  exit 1
fi

if [ ! -f web/package.json ]; then
  echo "missing frontend package.json under $REPO_ROOT/web" >&2
  exit 1
fi

npm --prefix web ci
npm --prefix web run build

sudo install -D -m 0644 deploy/systemd/whatsapp-chat-system.service /etc/systemd/system/whatsapp-chat-system.service
sudo systemctl daemon-reload
sudo systemctl enable --now whatsapp-chat-system.service
sudo systemctl restart whatsapp-chat-system.service

curl --fail --silent http://127.0.0.1:${BACKEND_PORT}/api/health >/tmp/whatsapp-chat-system-health.json
cat /tmp/whatsapp-chat-system-health.json

echo

echo "Backend restarted with built frontend mounted from $REPO_ROOT/web/dist"
echo "Profile: $PROFILE_PATH"
