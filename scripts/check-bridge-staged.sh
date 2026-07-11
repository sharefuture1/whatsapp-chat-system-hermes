#!/usr/bin/env bash
set -euo pipefail

files=()
while IFS= read -r file; do
  [[ -n "$file" ]] && files+=("$file")
done < <(git diff --cached --name-only --diff-filter=ACMR -- 'bridge/src/*.js' 'bridge/src/**/*.js' 'bridge/tests/*.js' 'bridge/tests/**/*.js')

((${#files[@]} == 0)) && exit 0

for file in "${files[@]}"; do
  node --check "$file"
done
