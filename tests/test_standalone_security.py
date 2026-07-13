from __future__ import annotations

from types import SimpleNamespace

from whatsapp_chat_system.standalone_api import (
    _allowed_cors_origins,
    _login_policy,
    _recent_login_attempts,
)


def test_standalone_cors_uses_explicit_origins() -> None:
    assert _allowed_cors_origins(
        'https://whats.future1.us, https://ops.example.com/, *, ftp://bad.example'
    ) == [
        'https://whats.future1.us',
        'https://ops.example.com',
    ]


def test_standalone_cors_falls_back_when_configuration_is_empty_or_invalid() -> None:
    fallback = _allowed_cors_origins('')
    assert 'https://whats.future1.us' in fallback
    assert '*' not in fallback
    assert _allowed_cors_origins('*, file://invalid') == fallback


def test_login_policy_bounds_invalid_values() -> None:
    runtime = SimpleNamespace(
        web_settings={
            'auth_policy': {
                'max_attempts': 0,
                'window_seconds': 'not-a-number',
            }
        }
    )
    assert _login_policy(runtime) == (5, 300)

    runtime.web_settings['auth_policy'] = {
        'max_attempts': 8,
        'window_seconds': 900,
    }
    assert _login_policy(runtime) == (8, 900)


def test_recent_login_attempts_discards_invalid_and_expired_entries() -> None:
    assert _recent_login_attempts(
        [100.0, 150.0, 'bad', None, 199.0],
        now=200.0,
        window_seconds=60,
    ) == [150.0, 199.0]
