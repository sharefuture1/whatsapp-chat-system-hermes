# Security Cleanup Plan

## Scope
This plan covers repository-facing cleanup only. Do not delete user/runtime files blindly.

## Findings from current repo scan
- Removed live password references from tracked docs.
- Added ignore rules for common local evidence artifacts: `screenshots/`, `audit-artifacts/`, `.artifacts/screenshots/`, `.artifacts/audits/`, `*.har`.
- Current repo scan found no tracked or untracked files matching screenshot/audit/HAR patterns.

## Safe cleanup procedure
1. Search before deleting:
   - markdown/docs for password, token, API key, bootstrap secret references
   - local evidence artifacts such as screenshots, HAR exports, audit bundles
2. If a sensitive artifact is found, list exact paths first and confirm whether it is:
   - a runtime file that must stay local
   - a redact-and-keep artifact
   - a delete candidate
3. Rotate any secret that was copied into docs, chat logs, screenshots, or temporary notes.
4. Remove or redact only the listed artifacts.
5. Re-run search to confirm no live secret values remain in tracked docs.

## Runtime files to treat as sensitive
- Hermes profile-local `web-settings.json`
- session tokens and exported auth headers
- API keys and bootstrap secrets provided via environment or deployment secret stores

## Follow-up recommendations
- If future QA requires screenshots/HAR captures, keep them under ignored artifact directories only.
- Prefer tunnel/access-policy protection in front of the console in addition to application login.
- Keep runtime secret values out of README, TODO, deployment notes, and issue templates.
