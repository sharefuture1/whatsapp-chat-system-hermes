from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from whatsapp_chat_system.ai.provider import AIProviderError, WendingAIProvider
from whatsapp_chat_system.settings import AISettings


class _ChatHandler(BaseHTTPRequestHandler):
    paths: list[str] = []
    auth_headers: list[str] = []

    def do_POST(self) -> None:  # noqa: N802
        type(self).paths.append(self.path)
        type(self).auth_headers.append(self.headers.get("Authorization", ""))
        length = int(self.headers.get("Content-Length", "0"))
        json.loads(self.rfile.read(length))
        body = json.dumps(
            {
                "id": "req_mock",
                "choices": [{"message": {"content": '{"message":"ok"}'}}],
                "usage": {"total_tokens": 3},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_settings_defaults_do_not_require_hermes_config(monkeypatch, tmp_path):
    for name in (
        "WENDING_AI_BASE_URL",
        "WENDING_AI_API_KEY",
        "WENDING_AI_DEFAULT_MODEL",
        "WENDING_AI_TIMEOUT_SECONDS",
        "WENDING_AI_MAX_RETRIES",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = AISettings.from_env()

    assert not (tmp_path / "config.yaml").exists()
    assert settings.base_url == "https://wendingai.future1.us/v1"
    assert settings.default_model == "gpt-5.3-codex-spark"
    assert settings.timeout_seconds == 90
    assert settings.max_retries == 2
    assert settings.safe_dict() == {
        "provider": "wendingai",
        "base_url": "https://wendingai.future1.us/v1",
        "default_model": "gpt-5.3-codex-spark",
        "timeout_seconds": 90,
        "max_retries": 2,
        "api_key_configured": False,
    }


def test_provider_posts_to_v1_chat_completions():
    _ChatHandler.paths = []
    _ChatHandler.auth_headers = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = AISettings(
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="unit-test-secret",
            default_model="test-model",
            timeout_seconds=2,
            max_retries=0,
        )
        result = WendingAIProvider(settings).chat(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert _ChatHandler.paths == ["/v1/chat/completions"]
    assert _ChatHandler.auth_headers == ["Bearer unit-test-secret"]
    assert result.content == '{"message":"ok"}'
    assert result.request_id == "req_mock"
    assert result.usage == {"total_tokens": 3}


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"error": {"message": "upstream failed"}}
        self.headers = {"X-Request-ID": "req_error"}

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.mark.parametrize(
    ("status", "code", "retryable", "expected_calls"),
    [
        (401, "authentication_error", False, 1),
        (429, "rate_limited", True, 3),
        (500, "upstream_error", True, 3),
    ],
)
def test_provider_maps_http_errors_and_retries_only_retryable(
    status, code, retryable, expected_calls
):
    session = _FakeSession([_FakeResponse(status) for _ in range(expected_calls)])
    settings = AISettings(api_key="unit-test-secret", max_retries=2)
    provider = WendingAIProvider(settings, session=session, sleep=lambda _: None)

    with pytest.raises(AIProviderError) as caught:
        provider.chat(model="m", messages=[])

    assert session.calls == expected_calls
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert caught.value.status_code == status
    assert caught.value.request_id == "req_error"
    assert "unit-test-secret" not in str(caught.value)
    assert "unit-test-secret" not in repr(caught.value)


def test_provider_maps_timeout_and_retries_finitely():
    session = _FakeSession([requests.Timeout("socket timeout") for _ in range(3)])
    provider = WendingAIProvider(
        AISettings(api_key="unit-test-secret", max_retries=2),
        session=session,
        sleep=lambda _: None,
    )

    with pytest.raises(AIProviderError) as caught:
        provider.chat(model="m", messages=[])

    assert session.calls == 3
    assert caught.value.code == "timeout"
    assert caught.value.retryable is True
    assert caught.value.status_code is None


def test_settings_normalize_and_bound_environment_values():
    settings = AISettings.from_env(
        {
            "WENDING_AI_BASE_URL": "https://user:secret@wendingai.future1.us/v1/?token=hidden",
            "WENDING_AI_API_KEY": "  unit-test-secret  ",
            "WENDING_AI_DEFAULT_MODEL": "  test-model  ",
            "WENDING_AI_TIMEOUT_SECONDS": "0",
            "WENDING_AI_MAX_RETRIES": "99",
        }
    )

    assert settings.api_key == "unit-test-secret"
    assert settings.default_model == "test-model"
    assert settings.timeout_seconds == 90
    assert settings.max_retries == 2
    assert settings.base_url == "https://wendingai.future1.us/v1"
    assert "secret" not in str(settings.safe_dict())
    assert "hidden" not in str(settings.safe_dict())

    blank_model = AISettings.from_env({"WENDING_AI_DEFAULT_MODEL": "   "})
    invalid_port = AISettings.from_env(
        {"WENDING_AI_BASE_URL": "https://example.com:99999/v1"}
    )
    assert blank_model.default_model == "gpt-5.3-codex-spark"
    assert invalid_port.base_url == "https://wendingai.future1.us/v1"


def test_provider_default_session_is_per_call_and_closed(monkeypatch):
    sessions = []

    class ClosingSession(_FakeSession):
        def __init__(self):
            super().__init__(
                [
                    _FakeResponse(
                        200,
                        {
                            "id": "req_ok",
                            "choices": [{"message": {"content": "ok"}}],
                        },
                    )
                ]
            )
            self.closed = False

        def close(self):
            self.closed = True

    def make_session():
        session = ClosingSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(requests, "Session", make_session)
    provider = WendingAIProvider(AISettings(api_key="unit-test-secret", max_retries=0))

    provider.chat(model="m", messages=[])
    provider.chat(model="m", messages=[])

    assert len(sessions) == 2
    assert all(session.closed for session in sessions)


def test_provider_maps_invalid_timeout_to_configuration_error():
    provider = WendingAIProvider(
        AISettings(api_key="unit-test-secret", timeout_seconds=0)
    )

    with pytest.raises(AIProviderError) as caught:
        provider.chat(model="m", messages=[])

    assert caught.value.code == "configuration_error"
    assert caught.value.retryable is False


def test_provider_uses_runtime_retry_override_for_http_errors():
    class RuntimeSettings:
        effective_base_url = "https://wendingai.future1.us/v1"
        effective_api_key = "unit-test-secret"
        effective_timeout = 2
        effective_retries = 2

    session = _FakeSession([_FakeResponse(500) for _ in range(3)])
    provider = WendingAIProvider(
        AISettings(api_key="unit-test-secret", max_retries=0),
        session=session,
        sleep=lambda _: None,
    )
    provider.set_runtime_manager(RuntimeSettings())

    with pytest.raises(AIProviderError) as caught:
        provider.chat(model="m", messages=[])

    assert session.calls == 3
    assert caught.value.code == "upstream_error"
