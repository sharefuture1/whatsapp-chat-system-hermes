# 2026-09-11 AI language and translation reliability

## Scope / requirements
FR-AI-003/004/005/008/010/011, PERF-003/004/006, NFR-REL-002.

## Observed production evidence
- API and SPA probes return 200; one WhatsApp account online, one QR pending.
- Account auto-reply modes and 95 conversation modes are off. Do not mass-enable or send test messages to contacts.
- DB AI configuration exists and a synthetic Thai/Lao -> Chinese probe succeeds with the configured model.
- Failed translations report configuration_error after settings were saved. The update endpoint persists DB changes but does not refresh the long-lived runtime manager; model resolution also uses the startup model.
- Translation batches report completed even with failed rows; client polls for under two seconds through a five-second GET cache.

## Implementation
1. Tests first: save AI settings must update live credentials/model; cached Rewriter must select live model.
2. Translation pipeline: invalid/empty unchanged results fail explicitly; preserve exact source hashes; report partial failure; reuse pending same-window batches; reject unsupported targets rather than mislabel Chinese as another language.
3. UI: network-first fetch bypasses cache/dedupe, wait with abort for a bounded batch poll, latest untranslated anchor first, no configuration errors swallowed.
4. Auto-reply: select language from latest meaningful inbound text (never the operator or page locale), fall back to contact preference for ambiguous input, include explicit language instruction, block clearly wrong-script output; recheck opt-out after AI call.
5. Remove corrupt hardcoded Thai/Lao glossary and summary-length restriction from translation prompt.

## Standard build-artifact release path (MIG-001)

Source files in the production checkout stay root-owned. Test a normal wheel installation into the production virtualenv instead of changing source-file permissions; migration assets remain under the service WorkingDirectory and must be discovered explicitly or startup fails closed. Keep the original checkout available for pip editable rollback. Frontend can be built to the configured Nginx dist output directory without emptying it, preserving old hashed assets. Do not execute generated copy scripts. Test installed-package migration lookup before attempting a package release. Prior Bridge source changes are not included in a Python wheel and must not be claimed as deployed by this path.

## Gates
Focused RED/GREEN, full Python/Web/Bridge tests, Ruff on changed Python, Vite browser/Tauri builds, secret/diff review. Read-only production diagnostics and synthetic AI probes; no real WhatsApp sends. Preserve existing pending contact-sync edits, user configuration, DB and sessions. Deploy with rollback and verify bundle hashes, API/Bridge and translation results. Git push only through permitted existing authentication; never echo credentials or put them in URLs or Git.
