from __future__ import annotations

import json

import pytest
import requests

from whatsapp_chat_system.bridge.client import BridgeClient, BridgeError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_all_requests_include_internal_token_and_explicit_timeouts():
    session = FakeSession(FakeResponse(200, {"status": "offline"}))
    client = BridgeClient(
        base_url="http://127.0.0.1:3100", internal_token="secret", session=session
    )

    client.status("account-a")

    _, url, kwargs = session.calls[0]
    assert url == "http://127.0.0.1:3100/accounts/account-a/status"
    assert kwargs["headers"]["X-Internal-Token"] == "secret"
    assert kwargs["timeout"] == (2.0, 10.0)


@pytest.mark.parametrize(
    ("response", "expected_code", "retryable"),
    [
        (
            FakeResponse(401, {"error": {"message": "bad token"}}),
            "bridge_unauthorized",
            False,
        ),
        (
            FakeResponse(503, {"error": {"message": "warming"}}),
            "bridge_unavailable",
            True,
        ),
        (
            FakeResponse(
                409,
                {
                    "error": {
                        "code": "account_offline",
                        "message": "offline",
                        "retryable": True,
                    }
                },
            ),
            "account_offline",
            True,
        ),
    ],
)
def test_http_errors_are_structured(response, expected_code, retryable):
    client = BridgeClient(
        base_url="http://localhost:3100",
        internal_token="secret",
        session=FakeSession(response),
    )

    with pytest.raises(BridgeError) as raised:
        client.connect("account-a")

    assert raised.value.code == expected_code
    assert raised.value.retryable is retryable


def test_timeout_is_structured_retryable_error():
    client = BridgeClient(
        base_url="http://localhost:3100",
        internal_token="secret",
        session=FakeSession(error=requests.Timeout("late")),
    )

    with pytest.raises(BridgeError) as raised:
        client.status("account-a")

    assert raised.value.code == "bridge_timeout"
    assert raised.value.retryable is True


def test_send_200_without_real_message_id_is_failure():
    client = BridgeClient(
        base_url="http://localhost:3100",
        internal_token="secret",
        session=FakeSession(FakeResponse(200, {"success": True})),
    )

    with pytest.raises(BridgeError) as raised:
        client.send("account-a", chat_id="123@s.whatsapp.net", text="hello")

    assert raised.value.code == "missing_message_id"
    assert raised.value.retryable is True


def test_qr_410_preserves_qr_expired():
    client = BridgeClient(
        base_url="http://localhost:3100",
        internal_token="secret",
        session=FakeSession(FakeResponse(410, {"error": {"code": "qr_expired"}})),
    )

    with pytest.raises(BridgeError) as raised:
        client.qr("account-a")

    assert raised.value.code == "qr_expired"
    assert raised.value.retryable is True


def test_external_bridge_host_is_rejected_by_default():
    with pytest.raises(ValueError, match="loopback"):
        BridgeClient(base_url="https://bridge.example.com", internal_token="secret")
