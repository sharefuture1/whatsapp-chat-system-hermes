#!/usr/bin/env bash
set -euo pipefail

# LEGACY ONLY — DO NOT USE FOR STANDALONE CUTOVER.
# This historical helper depends on the former deployment path and is retained
# exclusively for approved legacy rollback/diagnostic work.
echo "BLOCKED: deploy/apply-production.sh is legacy-only and must not be used for standalone cutover." >&2
echo "Use the approved standalone migration checklist after all readiness gates pass." >&2
exit 64
