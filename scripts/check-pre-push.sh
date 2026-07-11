#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

case "${1:-all}" in
  python)
    ./.venv/bin/pytest -q
    ;;
  web)
    (
      cd web
      node --test tests/*.test.js
      npm run build
    )
    ;;
  bridge)
    (
      cd bridge
      npm test
      npm run lint
    )
    ;;
  all)
    "$0" python
    "$0" web
    "$0" bridge
    ;;
  *)
    echo "usage: $0 {python|web|bridge|all}" >&2
    exit 2
    ;;
esac
