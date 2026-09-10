"""内部事件接口的 HMAC 签名、时间戳窗口与重放防护。

修复前该接口只有静态共享 token：token 泄露即可注入任意事件，
且抓到的请求可以无限期重放。
"""

from __future__ import annotations

import json
import time

import pytest
from conftest import create_profile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import WhatsAppAccount
from whatsapp_chat_system.security.internal_auth import (
    InternalAuthError,
    InternalAuthHeaders,
    ReplayGuard,
    compute_signature,
    verify_internal_request,
    verify_request_signature,
)
from whatsapp_chat_system.web_api import build_app

TOKEN = "internal-test-secret"
SECRET = "hmac-test-secret"


def _payload(event_id: str = "evt-sig-1", sequence: int = 1) -> dict:
    return {
        "event_id": event_id,
        "event_type": "message.upsert",
        "account_id": "account-a",
        "occurred_at": "2026-07-10T00:00:00Z",
        "sequence": sequence,
        "payload": {
            "schema_version": 1,
            "wa_message_id": f"WA-{event_id}",
            "remote_jid": "8551@s.whatsapp.net",
            "sender_jid": "8551@s.whatsapp.net",
            "participant_jid": None,
            "from_me": False,
            "conversation_type": "dm",
            "message_type": "text",
            "timestamp": "2026-07-10T00:00:00Z",
            "text": "hello",
            "push_name": "Customer",
            "quoted_wa_message_id": None,
            "media": None,
        },
    }


def _build_client(tmp_path, *, with_signature: bool) -> TestClient:
    engine = create_engine(f"sqlite:///{tmp_path / 'sig.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    profile = create_profile(tmp_path / "profile")
    with factory() as db:
        db.add(
            WhatsAppAccount(id="account-a", name="A", session_ref="account:account-a")
        )
        db.commit()
    client = TestClient(
        build_app(
            str(profile), account_session_factory=factory, internal_event_token=TOKEN
        )
    )
    client._engine = engine  # type: ignore[attr-defined]
    return client


@pytest.fixture()
def unsigned_client(tmp_path, monkeypatch):
    monkeypatch.delenv("WHATSAPP_BRIDGE_HMAC_SECRET", raising=False)
    client = _build_client(tmp_path, with_signature=False)
    yield client
    client._engine.dispose()  # type: ignore[attr-defined]


@pytest.fixture()
def signed_client(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_BRIDGE_HMAC_SECRET", SECRET)
    client = _build_client(tmp_path, with_signature=True)
    yield client
    client._engine.dispose()  # type: ignore[attr-defined]


def _sign(secret: str, body: bytes, *, timestamp: str | None = None, nonce: str | None = None):
    stamp = timestamp if timestamp is not None else str(int(time.time()))
    headers = {
        "X-Internal-Token": TOKEN,
        "X-Internal-Timestamp": stamp,
        "X-Internal-Signature": compute_signature(secret, stamp, body),
    }
    if nonce is not None:
        headers["X-Internal-Nonce"] = nonce
    return headers


def _post(client: TestClient, body: dict, headers: dict):
    raw = json.dumps(body).encode()
    return client.post(
        "/internal/events/whatsapp",
        content=raw,
        headers={**headers, "Content-Type": "application/json"},
    )


def test_static_token_still_works_without_hmac_configured(unsigned_client):
    """未配置签名密钥时保持旧的单 token 行为，避免破坏既有 Bridge。"""

    response = _post(unsigned_client, _payload(), {"X-Internal-Token": TOKEN})

    assert response.status_code == 200
    assert response.json()["accepted"] is True


def test_missing_signature_is_rejected_when_hmac_configured(signed_client):
    response = _post(signed_client, _payload(), {"X-Internal-Token": TOKEN})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_signature"


def test_valid_signature_is_accepted(signed_client):
    raw = json.dumps(_payload()).encode()
    response = _post(
        signed_client,
        _payload(),
        _sign(SECRET, raw, nonce="nonce-1"),
    )

    assert response.status_code == 200
    assert response.json()["accepted"] is True


def test_tampered_body_invalidates_signature(signed_client):
    """签名只对原始字节有效：改一个字符即失败。"""

    raw = json.dumps(_payload()).encode()
    headers = _sign(SECRET, raw)

    tampered = _payload()
    tampered["payload"]["text"] = "tampered"
    response = _post(signed_client, tampered, headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_signature"


def test_wrong_secret_is_rejected(signed_client):
    raw = json.dumps(_payload()).encode()
    response = _post(signed_client, _payload(), _sign("wrong-secret", raw))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_signature"


def test_stale_timestamp_is_rejected(signed_client):
    raw = json.dumps(_payload()).encode()
    old = str(int(time.time()) - 3600)
    response = _post(signed_client, _payload(), _sign(SECRET, raw, timestamp=old))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "stale_signature"


def test_far_future_timestamp_is_rejected(signed_client):
    """不能签发一个「未来」时间戳来延长重放窗口。"""

    raw = json.dumps(_payload()).encode()
    future = str(int(time.time()) + 86_400)
    response = _post(signed_client, _payload(), _sign(SECRET, raw, timestamp=future))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "stale_signature"


def test_replayed_nonce_is_rejected(signed_client):
    first_body = _payload(event_id="evt-a")
    headers = _sign(
        SECRET, json.dumps(first_body).encode(), nonce="fixed-nonce"
    )

    first = _post(signed_client, first_body, headers)
    # 换一个 event_id 再投一次，但 nonce 相同 → 应判为重放
    second_body = _payload(event_id="evt-b")
    second = _post(signed_client, second_body, _sign(
        SECRET, json.dumps(second_body).encode(), nonce="fixed-nonce"
    ))

    assert first.status_code == 200
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "replayed_request"


def test_same_nonce_with_different_event_is_still_replay(signed_client):
    """重放防护基于 nonce，而非 event_id——否则换个 event_id 就能绕过。"""

    first_body = _payload(event_id="evt-1")
    _post(
        signed_client,
        first_body,
        _sign(SECRET, json.dumps(first_body).encode(), nonce="dup-nonce"),
    )

    second_body = _payload(event_id="evt-2")
    replay = _post(
        signed_client,
        second_body,
        _sign(SECRET, json.dumps(second_body).encode(), nonce="dup-nonce"),
    )

    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "replayed_request"


def test_valid_signature_but_wrong_token_is_rejected(signed_client):
    """签名与 token 是两层独立校验，缺一不可。"""

    body = _payload()
    raw = json.dumps(body).encode()
    headers = _sign(SECRET, raw)
    headers["X-Internal-Token"] = "wrong-token"

    response = _post(signed_client, body, headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_token"


def test_auth_precedes_body_validation(signed_client):
    """未鉴权的畸形 payload 不能探测 schema（应返回 401 而非 422）。"""

    response = signed_client.post(
        "/internal/events/whatsapp",
        content=b'{"not":"an envelope"}',
        headers={"X-Internal-Token": "wrong", "Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_token"


def test_error_response_keeps_structured_shape(signed_client):
    response = _post(signed_client, _payload(), {"X-Internal-Token": TOKEN})

    error = response.json()["error"]
    assert set(error) >= {"code", "message", "retryable", "request_id", "details"}
    assert error["retryable"] is False
    assert response.headers.get("X-Request-ID")


def test_event_id_idempotency_still_applies_with_signature(signed_client):
    """签名之上仍有 event_id 幂等，重复投递同一事件返回 duplicate。"""

    raw = json.dumps(_payload()).encode()
    first = _post(signed_client, _payload(), _sign(SECRET, raw, nonce="n-1"))
    fresh_raw = json.dumps(_payload()).encode()
    second = _post(signed_client, _payload(), _sign(SECRET, fresh_raw, nonce="n-2"))

    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["duplicate"] is True


# --------------------------------------------------------------------- 单元层


def test_replay_guard_expires_entries():
    clock = {"now": 1000.0}
    guard = ReplayGuard(ttl_seconds=60.0)
    guard._clock = lambda: clock["now"]  # type: ignore[method-assign]

    assert guard.check_and_record("n1") is True
    assert guard.check_and_record("n1") is False

    clock["now"] += 61
    assert guard.check_and_record("n1") is True


def test_replay_guard_empty_nonce_is_always_allowed():
    guard = ReplayGuard()
    assert guard.check_and_record("") is True
    assert guard.check_and_record("") is True


def test_replay_guard_is_thread_safe():
    import threading

    guard = ReplayGuard()
    results: list[bool] = []
    lock = threading.Lock()

    def worker():
        outcome = guard.check_and_record("shared")
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1


def test_verify_request_signature_uses_injected_clock():
    body = b'{"a":1}'
    stamp = "5000"
    headers = InternalAuthHeaders(
        timestamp=stamp, signature=compute_signature(SECRET, stamp, body)
    )

    # 时间戳落在窗口内：通过
    verify_request_signature(secret=SECRET, headers=headers, body=body, now=5100.0)

    # 超出窗口：拒绝
    with pytest.raises(InternalAuthError) as excinfo:
        verify_request_signature(secret=SECRET, headers=headers, body=body, now=9000.0)
    assert excinfo.value.code == "stale_signature"


def test_verify_internal_request_warns_but_allows_without_secret():
    verify_internal_request(
        configured_token=TOKEN,
        headers=InternalAuthHeaders(token=TOKEN),
        body=b"{}",
        hmac_secret=None,
    )


def test_verify_internal_request_requires_secret_be_non_empty_string():
    with pytest.raises(InternalAuthError) as excinfo:
        verify_request_signature(
            secret="",
            headers=InternalAuthHeaders(timestamp="1", signature="x"),
            body=b"",
        )
    assert excinfo.value.code == "internal_signature_not_configured"


def test_invalid_timestamp_format_is_rejected():
    with pytest.raises(InternalAuthError) as excinfo:
        verify_request_signature(
            secret=SECRET,
            headers=InternalAuthHeaders(timestamp="not-a-number", signature="x"),
            body=b"",
        )
    assert excinfo.value.code == "invalid_timestamp"
