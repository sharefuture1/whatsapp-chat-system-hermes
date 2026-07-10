from __future__ import annotations

import secrets


class InternalAuthError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def verify_internal_token(configured_token: str, presented_token: str | None) -> None:
    if not configured_token:
        raise InternalAuthError(
            'internal_events_not_configured',
            'WhatsApp internal event token is not configured',
            status_code=503,
        )
    if not presented_token or not secrets.compare_digest(configured_token, presented_token):
        raise InternalAuthError('invalid_internal_token', 'Invalid internal token', status_code=401)
