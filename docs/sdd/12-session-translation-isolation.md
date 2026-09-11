# Session and translation isolation — Round 1

Status: Approved for implementation; production verification is separate.

## SEC-CACHE-001 / PERF-008
Deferred cache work is bound to the login scope and an immutable generation.
Logout, scope changes and conversation deletion invalidate pending writes. Old
callbacks cannot recreate deleted data or write one user's data in another scope.
API requests may not publish results or auth events after the login generation
changes; writes invalidate old GET cache generations. Timeouts and cancellation
are bounded and distinguishable.

## SEC-AUTH-015
A user marked password_change_required keeps that flag after login. Until a
successful password change, authenticated API access is limited to /api/v1/me,
/api/v1/users/change-password and logout. The UI must show a mandatory change
screen, not the workspace. A successful change clears the flag and revokes all
sessions (including the current one); the user signs in using the new password.
Do not require a password change for existing users without this flag.

## DATA-004 / FR-AI-014 / TX-TRANS-001
Translation memory cannot be reused across account boundaries. All lookup paths
(inbound, batch endpoint, dispatcher) enforce account scope. Content version hashes
are SHA-256 of exact stored UTF-8 source text, preserving whitespace. Completed
records for an older source version cannot suppress new work. Memory reuse must
commit before the endpoint returns completed, and must update an existing failed
row rather than insert a conflicting unique key. Historical records are retained;
no production database reset or destructive migration is allowed.

## QA-ROUND-001
Write failing tests, then pass the complete Python/Web/Bridge suites and Browser/
Tauri builds. Python formatting must not prevent the separate pytest CI job from
running, while both remain required gates. No production Verified claim without
actual server service/version/HTTP checks. No automatic enabling of customer AI.
