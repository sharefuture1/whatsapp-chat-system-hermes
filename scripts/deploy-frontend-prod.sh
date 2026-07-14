#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/young11/workspace/whatsapp-chat-system-hermes"
WEB_DIR="$ROOT_DIR/web"
DIST_DIR="$WEB_DIR/dist"
DEPLOY_DIR="/opt/whatsapp-chat-system/web/dist"
PUBLIC_BASE="https://whats.future1.us"
HEALTH_URL="$PUBLIC_BASE/api/health"

cd "$WEB_DIR"
npm run build

INDEX_HTML="$DIST_DIR/index.html"
if [[ ! -f "$INDEX_HTML" ]]; then
  echo "ERROR: build output missing $INDEX_HTML" >&2
  exit 1
fi

JS_ASSET=$(python3 - <<'PY'
import re
from pathlib import Path
html = Path('dist/index.html').read_text(encoding='utf-8')
match = re.search(r"assets/index-[^\"']*\\.js", html)
print(match.group(0) if match else '')
PY
)
CSS_ASSET=$(python3 - <<'PY'
import re
from pathlib import Path
html = Path('dist/index.html').read_text(encoding='utf-8')
match = re.search(r"assets/index-[^\"']*\\.css", html)
print(match.group(0) if match else '')
PY
)
if [[ -z "$JS_ASSET" || -z "$CSS_ASSET" ]]; then
  echo "ERROR: unable to locate built asset names in index.html" >&2
  exit 1
fi

sudo rsync -r --delete "$DIST_DIR/" "$DEPLOY_DIR/"

if [[ ! -f "$DEPLOY_DIR/$JS_ASSET" ]]; then
  echo "ERROR: deployed JS asset missing: $DEPLOY_DIR/$JS_ASSET" >&2
  exit 1
fi
if [[ ! -f "$DEPLOY_DIR/$CSS_ASSET" ]]; then
  echo "ERROR: deployed CSS asset missing: $DEPLOY_DIR/$CSS_ASSET" >&2
  exit 1
fi

HTML=$(curl -fsS "$PUBLIC_BASE/")
if ! grep -q "$JS_ASSET" <<<"$HTML"; then
  echo "ERROR: production HTML does not reference expected JS asset $JS_ASSET" >&2
  exit 1
fi
if ! grep -q "$CSS_ASSET" <<<"$HTML"; then
  echo "ERROR: production HTML does not reference expected CSS asset $CSS_ASSET" >&2
  exit 1
fi

curl -fsS "$HEALTH_URL" >/dev/null
curl -fsSI "$PUBLIC_BASE/$JS_ASSET" | grep -q '200'
curl -fsSI "$PUBLIC_BASE/$CSS_ASSET" | grep -q '200'

echo "前端部署完成 ✅"
echo "JS:  $JS_ASSET"
echo "CSS: $CSS_ASSET"
echo "Health: $HEALTH_URL"
