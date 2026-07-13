from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from conftest import create_profile
from whatsapp_chat_system.bridge.client import BridgeError
from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.web_api import build_app


class FakeBridge:
    def __init__(self) -> None:
        self.calls = []
        self.qr_payload = {
            "account_id": "filled-by-test",
            "status": "qr_pending",
            "qr_data_url": "data:image/png;base64,ZmFrZQ==",
            "expires_at": "2026-07-10T12:00:00+00:00",
        }

    def create_account(self, account_id, session_ref):
        self.calls.append(("create", account_id, session_ref))
        return {"success": True}

    def list_accounts(self):
        self.calls.append(("list",))
        return {"items": [], "total": 0}

    def connect(self, account_id):
        self.calls.append(("connect", account_id))
        return {"accepted": True}

    def qr(self, account_id):
        self.calls.append(("qr", account_id))
        return {**self.qr_payload, "account_id": account_id}

    def logout(self, account_id):
        self.calls.append(("logout", account_id))
        return {"success": True}

    def stop(self, account_id):
        self.calls.append(("stop", account_id))
        return {"success": True}

    def delete(self, account_id, *, delete_session=False):
        self.calls.append(("delete", account_id, delete_session))
        return {"success": True}

    def send(self, account_id, *, chat_id, text, idempotency_key=None):
        self.calls.append(("send", account_id, chat_id, text, idempotency_key))
        return {"success": True, "message_id": "wa-real-1"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    database = tmp_path / "accounts.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    profile = create_profile(tmp_path / "profile")
    bridge = FakeBridge()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    client = TestClient(
        build_app(str(profile), account_session_factory=factory, account_bridge=bridge)
    )
    token = client.post("/api/login", json={"password": "test-pass"}).json()[
        "session_token"
    ]
    client.headers.update({"x-session-token": token})
    yield client, bridge, factory
    engine.dispose()


def create_account(client, name="Sales"):
    response = client.post(
        "/api/v1/accounts", json={"name": name, "auto_reply_mode": "suggest"}
    )
    assert response.status_code == 201
    return response.json()


def test_accounts_routes_reuse_legacy_auth(api):
    client, _, _ = api
    client.headers.pop("x-session-token")
    assert client.get("/api/v1/accounts").status_code == 401


def test_get_post_patch_accounts_and_safe_response(api):
    client, bridge, _ = api
    created = create_account(client)

    assert created["is_primary"] is True
    assert created["status"] == "new"
    assert "session_ref" not in created
    serialized = json.dumps(created).lower()
    assert "hermes" not in serialized
    assert "profile_path" not in serialized
    assert bridge.calls[0][0] == "create"

    updated = client.patch(
        f"/api/v1/accounts/{created['id']}",
        json={"name": "Sales Main", "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Sales Main"
    assert updated.json()["enabled"] is False
    assert ("stop", created["id"]) in bridge.calls

    listing = client.get("/api/v1/accounts")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["id"] == created["id"]


def test_connect_returns_202_without_premarking_online(api):
    client, bridge, _ = api
    account = create_account(client)

    response = client.post(f"/api/v1/accounts/{account['id']}/connect")

    assert response.status_code == 202
    assert response.json()["account"]["status"] == "new"
    assert ("connect", account["id"]) in bridge.calls
    assert client.get("/api/v1/accounts").json()["items"][0]["status"] == "new"


def test_qr_only_returns_when_account_is_qr_pending(api):
    client, bridge, factory = api
    account = create_account(client)

    rejected = client.get(f"/api/v1/accounts/{account['id']}/qr")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "qr_not_pending"

    with factory() as db:
        row = db.get(
            __import__(
                "whatsapp_chat_system.db.models", fromlist=["WhatsAppAccount"]
            ).WhatsAppAccount,
            account["id"],
        )
        row.status = "qr_pending"
        db.commit()

    accepted = client.get(f"/api/v1/accounts/{account['id']}/qr")
    assert accepted.status_code == 200
    assert accepted.json()["qr_data_url"].startswith("data:image/png;base64,")
    assert ("qr", account["id"]) in bridge.calls


def test_logout_preserves_business_account(api):
    client, bridge, _ = api
    account = create_account(client)

    response = client.post(f"/api/v1/accounts/{account['id']}/logout")

    assert response.status_code == 200
    assert response.json()["account"]["status"] == "logged_out"
    assert response.json()["account"]["enabled"] is False
    assert client.get("/api/v1/accounts").json()["items"][0]["id"] == account["id"]
    assert ("logout", account["id"]) in bridge.calls


def test_delete_requires_confirm_name_and_keeps_delete_session_independent(api):
    client, bridge, _ = api
    account = create_account(client)

    wrong = client.request(
        "DELETE",
        f"/api/v1/accounts/{account['id']}",
        json={"confirm_name": "wrong", "delete_session": True},
    )
    assert wrong.status_code == 409
    assert bridge.calls[-1][0] == "create"

    deleted = client.request(
        "DELETE",
        f"/api/v1/accounts/{account['id']}",
        json={"confirm_name": "Sales", "delete_session": False},
    )
    assert deleted.status_code == 200
    assert ("delete", account["id"], False) in bridge.calls
    assert client.get("/api/v1/accounts").json()["items"] == []


def test_bridge_unavailable_returns_structured_retryable_error(api):
    client, bridge, _ = api
    account = create_account(client)

    def unavailable(account_id):
        raise BridgeError(
            "bridge_unavailable", "offline", retryable=True, status_code=503
        )

    bridge.connect = unavailable
    response = client.post(f"/api/v1/accounts/{account['id']}/connect")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "bridge_unavailable"
    assert response.json()["error"]["retryable"] is True


def test_v2_reply_queues_then_worker_sends_and_persists_outbound_message(api):
    from whatsapp_chat_system.db.models import (
        Contact,
        Conversation,
        Message,
        OutboxMessage,
    )
    from whatsapp_chat_system.outbox import OutboxDispatcher

    client, bridge, factory = api
    account = create_account(client, "WA2")
    with factory() as db:
        contact = Contact(
            account_id=account["id"],
            remote_jid="person@lid",
            display_name="Person",
        )
        db.add(contact)
        db.flush()
        conversation = Conversation(
            account_id=account["id"],
            contact_id=contact.id,
            remote_jid="person@lid",
        )
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/reply",
        json={"message": "hello", "idempotency_key": "client-msg-1"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["queued"] is True
    assert body["message_id"] is None
    assert body["local_message_id"]
    assert body["outbox_id"]
    assert not any(call[0] == "send" for call in bridge.calls)

    duplicate = client.post(
        f"/api/v1/conversations/{conversation_id}/reply",
        json={"message": "hello", "idempotency_key": "client-msg-1"},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["created"] is False
    assert duplicate.json()["local_message_id"] == body["local_message_id"]

    with factory() as db:
        row = db.get(Message, body["local_message_id"])
        outbox = db.get(OutboxMessage, body["outbox_id"])
        assert row.account_id == account["id"]
        assert row.conversation_id == conversation_id
        assert row.direction == "outbound"
        assert row.status == "queued"
        assert row.wa_message_id is None
        assert row.content == "hello"
        assert outbox.status == "pending"
        assert outbox.message_id == row.id

    assert OutboxDispatcher(factory, bridge).run_once() == 1
    assert (
        "send",
        account["id"],
        "person@lid",
        "hello",
        "reply:client-msg-1",
    ) in bridge.calls
    with factory() as db:
        row = db.get(Message, body["local_message_id"])
        outbox = db.get(OutboxMessage, body["outbox_id"])
        assert row.status == "sent"
        assert row.wa_message_id == "wa-real-1"
        assert outbox.status == "completed"


def test_create_bridge_failure_compensates_database_row(api):
    client, bridge, _ = api

    def unavailable(account_id, session_ref):
        raise BridgeError(
            "bridge_unavailable", "offline", retryable=True, status_code=503
        )

    bridge.create_account = unavailable
    response = client.post("/api/v1/accounts", json={"name": "Orphan Guard"})

    assert response.status_code == 503
    assert client.get("/api/v1/accounts").json()["items"] == []


def test_disable_bridge_failure_keeps_account_enabled(api):
    client, bridge, _ = api
    account = create_account(client)

    def unavailable(account_id):
        raise BridgeError(
            "bridge_unavailable", "offline", retryable=True, status_code=503
        )

    bridge.stop = unavailable
    response = client.patch(
        f"/api/v1/accounts/{account['id']}", json={"enabled": False}
    )

    assert response.status_code == 503
    assert client.get("/api/v1/accounts").json()["items"][0]["enabled"] is True


def test_patch_rejects_null_account_name(api):
    client, _, _ = api
    account = create_account(client)

    response = client.patch(f"/api/v1/accounts/{account['id']}", json={"name": None})

    assert response.status_code == 422


def test_lifespan_reconciles_on_startup_and_cancels_background_task(
    tmp_path, monkeypatch
):
    from whatsapp_chat_system.db.models import WhatsAppAccount

    database = tmp_path / "startup-reconcile.db"
    engine = create_engine(
        f"sqlite:///{database}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as db:
        db.add(
            WhatsAppAccount(
                id="WA2",
                name="WA2",
                session_ref="account:WA2",
                enabled=True,
                status="offline",
            )
        )
        db.commit()
    profile = create_profile(tmp_path / "startup-profile")
    bridge = FakeBridge()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    app = build_app(
        str(profile),
        account_session_factory=factory,
        account_bridge=bridge,
        account_reconcile_interval_seconds=3600,
    )

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        for _ in range(100):
            if ("connect", "WA2") in bridge.calls:
                break
            __import__("time").sleep(0.01)
        assert ("create", "WA2", "account:WA2") in bridge.calls
        assert ("connect", "WA2") in bridge.calls
        task = app.state.account_reconciler_task
        assert task.done() is False

    assert task.done() is True
    assert task.cancelled() is True
    engine.dispose()
