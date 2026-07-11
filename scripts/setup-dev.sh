#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi

./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e . pytest pre-commit ruff
npm --prefix web ci
npm --prefix bridge ci

./.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
./.venv/bin/pre-commit install-hooks

printf '\nDevelopment checks installed.\n'
printf 'Fast checks: ./.venv/bin/pre-commit run --all-files\n'
printf 'Full checks: ./.venv/bin/pre-commit run --hook-stage pre-push --all-files\n'
