from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    MessageTranslation,
    WhatsAppAccount,
)
from whatsapp_chat_system.standalone_api import (
    _current_alembic_head,
    build_standalone_app,
)
from whatsapp_chat_system.web_api import build_app as build_compat_app


ADMIN_PASSWORD = "standalone-security-password"
USER_PASSWORD = "standalone-role-password"


class _FakeBridge:
    def list_accounts(self) -> dict[str, object]:
        return {"items": [], "total": 0}

    def send(self, *args, **kwargs) -> dict[str, object]:
        raise AssertionError("security tests must not deliver queued messages")


@pytest.fixture
def security_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = tmp_path / "security.db"
    database_url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("WHATSAPP_BRIDGE_INTERNAL_TOKEN", "security-test-token")
    monkeypatch.setenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("WENDING_AI_API_KEY", "stored-ai-test-key")

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": _current_alembic_head()},
        )
    factory = sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )
    app = build_standalone_app(
        runtime_dir=tmp_path / "runtime",
        account_session_factory=factory,
        account_bridge=_FakeBridge(),
        account_reconcile_interval_seconds=3600,
        outbox_poll_interval_seconds=3600,
    )
    with TestClient(app) as client:
        yield client, app, factory
    engine.dispose()


def _login(client: TestClient, username: str = "admin") -> str:
    response = client.post(
        "/api/login",
        json={
            "username": username,
            "password": ADMIN_PASSWORD if username == "admin" else USER_PASSWORD,
        },
    )
    assert response.status_code == 200
    return response.json()["session_token"]


def _register_user(
    client: TestClient,
    admin_token: str,
    *,
    username: str,
    role: str,
    account_ids: list[str] | None = None,
) -> str:
    response = client.post(
        "/api/v1/users/register",
        headers={"x-session-token": admin_token},
        json={
            "username": username,
            "password": USER_PASSWORD,
            "role": role,
            "allowed_account_ids": account_ids or [],
        },
    )
    assert response.status_code == 201
    return _login(client, username)


def _seed_conversations(factory: sessionmaker[Session]) -> dict[str, str]:
    with factory() as session:
        first_account = WhatsAppAccount(
            name="Allowed account",
            session_ref="security/allowed",
            enabled=False,
        )
        second_account = WhatsAppAccount(
            name="Foreign account",
            session_ref="security/foreign",
            enabled=False,
        )
        session.add_all([first_account, second_account])
        session.flush()

        first_contact = Contact(
            account_id=first_account.id,
            remote_jid="allowed@lid",
            display_name="Allowed",
        )
        second_contact = Contact(
            account_id=second_account.id,
            remote_jid="foreign@lid",
            display_name="Foreign",
        )
        session.add_all([first_contact, second_contact])
        session.flush()

        first_conversation = Conversation(
            account_id=first_account.id,
            contact_id=first_contact.id,
            remote_jid=first_contact.remote_jid,
        )
        second_conversation = Conversation(
            account_id=second_account.id,
            contact_id=second_contact.id,
            remote_jid=second_contact.remote_jid,
        )
        session.add_all([first_conversation, second_conversation])
        session.flush()
        first_conversation.unread_count = 2
        second_conversation.unread_count = 2
        allowed_message = Message(
            account_id=first_account.id,
            conversation_id=first_conversation.id,
            contact_id=first_contact.id,
            direction="inbound",
            message_type="text",
            content="允许账号消息",
            status="received",
        )
        foreign_message = Message(
            account_id=second_account.id,
            conversation_id=second_conversation.id,
            contact_id=second_contact.id,
            direction="inbound",
            message_type="text",
            content="其他账号消息",
            status="received",
        )
        session.add_all([allowed_message, foreign_message])
        session.commit()
        return {
            "allowed_account": first_account.id,
            "foreign_account": second_account.id,
            "allowed_contact": first_contact.id,
            "foreign_contact": second_contact.id,
            "allowed_conversation": first_conversation.id,
            "foreign_conversation": second_conversation.id,
            "allowed_message": allowed_message.id,
            "foreign_message": foreign_message.id,
        }


def test_settings_response_uses_allowlist_and_recursively_removes_credentials(
    security_api,
):
    client, app, _ = security_api
    admin_token = _login(client)
    _register_user(
        client,
        admin_token,
        username="viewer",
        role="viewer",
    )
    app.state.runtime.web_settings["reply"] = {
        "tone": "warm",
        "api_key": "must-not-leak",
        "nested": {"token": "must-not-leak", "style": "brief"},
    }
    app.state.runtime.web_settings["plugins"] = {
        "auto_translate": True,
        "api_key": "must-not-leak",
    }

    response = client.get(
        "/api/v1/settings",
        headers={"x-session-token": admin_token},
    )

    assert response.status_code == 200
    web_settings = response.json()["web_settings"]
    assert set(web_settings) <= {"ui", "message_ops", "reply", "plugins"}
    assert web_settings["reply"] == {
        "tone": "warm",
        "nested": {"style": "brief"},
    }
    assert response.json()["plugins"] == {"auto_translate": True}
    serialized = str(web_settings).lower()
    for forbidden in ("users", "sessions", "salt", "hash", "api_key", "token"):
        assert forbidden not in serialized


def test_ai_connection_test_requires_admin_and_rejects_unsafe_key_url_pairs(
    security_api,
    monkeypatch: pytest.MonkeyPatch,
):
    from whatsapp_chat_system.ai import provider as provider_module

    client, _, _ = security_api
    admin_token = _login(client)
    operator_token = _register_user(
        client,
        admin_token,
        username="operator",
        role="operator",
    )
    calls: list[object] = []

    class _Provider:
        def __init__(self, settings):
            calls.append(settings)

        def chat(self, **kwargs):
            return SimpleNamespace(model="security-test-model")

    monkeypatch.setattr(provider_module, "WendingAIProvider", _Provider)

    forbidden_role = client.post(
        "/api/v1/ai/test",
        headers={"x-session-token": operator_token},
        json={"base_url": "https://8.8.8.8/v1", "api_key": "caller-key"},
    )
    mixed_credentials = client.post(
        "/api/v1/ai/test",
        headers={"x-session-token": admin_token},
        json={"base_url": "https://8.8.8.8/v1"},
    )
    private_target = client.post(
        "/api/v1/ai/test",
        headers={"x-session-token": admin_token},
        json={"base_url": "https://127.0.0.1/v1", "api_key": "caller-key"},
    )

    assert forbidden_role.status_code == 403
    assert mixed_credentials.status_code == 422
    assert mixed_credentials.json()["detail"]["code"] == (
        "api_key_required_for_custom_base_url"
    )
    assert private_target.status_code == 422
    assert private_target.json()["detail"]["code"] == "unsafe_ai_base_url"
    assert calls == []

    accepted = client.post(
        "/api/v1/ai/test",
        headers={"x-session-token": admin_token},
        json={"base_url": "https://8.8.8.8/v1", "api_key": "caller-key"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["ok"] is True
    assert len(calls) == 1
    assert calls[0].base_url == "https://8.8.8.8/v1"
    assert calls[0].api_key == "caller-key"


def test_ai_connection_test_rejects_dns_answers_containing_private_addresses(
    security_api,
    monkeypatch: pytest.MonkeyPatch,
):
    from whatsapp_chat_system.api.v1 import settings as settings_module

    client, _, _ = security_api
    admin_token = _login(client)

    monkeypatch.setattr(
        settings_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.8", 443)),
        ],
    )
    response = client.post(
        "/api/v1/ai/test",
        headers={"x-session-token": admin_token},
        json={
            "base_url": "https://ai.example.test/v1",
            "api_key": "caller-key",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsafe_ai_base_url"


def test_operations_enforce_roles_account_scope_and_broadcast_gate(security_api):
    client, app, factory = security_api
    ids = _seed_conversations(factory)
    admin_token = _login(client)
    operator_token = _register_user(
        client,
        admin_token,
        username="operator",
        role="operator",
        account_ids=[ids["allowed_account"]],
    )
    viewer_token = _register_user(
        client,
        admin_token,
        username="viewer",
        role="viewer",
        account_ids=[ids["allowed_account"]],
    )
    run_at = datetime.now(timezone.utc).timestamp() + 3600

    foreign = client.post(
        "/api/v1/schedule",
        headers={"x-session-token": admin_token},
        json={
            "target": ids["foreign_conversation"],
            "message": "foreign",
            "run_at": run_at,
        },
    )
    own = client.post(
        "/api/v1/schedule",
        headers={"x-session-token": operator_token},
        json={
            "target": ids["allowed_conversation"],
            "message": "allowed",
            "run_at": run_at,
        },
    )
    viewer_write = client.post(
        "/api/v1/schedule",
        headers={"x-session-token": viewer_token},
        json={
            "target": ids["allowed_conversation"],
            "message": "not allowed",
            "run_at": run_at,
        },
    )
    foreign_write = client.post(
        "/api/v1/schedule",
        headers={"x-session-token": operator_token},
        json={
            "target": ids["foreign_conversation"],
            "message": "not visible",
            "run_at": run_at,
        },
    )

    assert foreign.status_code == 202
    assert own.status_code == 202
    assert viewer_write.status_code == 403
    assert foreign_write.status_code == 404

    overlong_key = client.post(
        "/api/v1/schedule",
        headers={"x-session-token": operator_token},
        json={
            "target": ids["allowed_conversation"],
            "message": "invalid idempotency key",
            "run_at": run_at,
            "idempotency_key": "x" * 247,
        },
    )
    assert overlong_key.status_code == 422

    schedule_items = client.get(
        "/api/v1/schedule",
        headers={"x-session-token": operator_token},
    ).json()["items"]
    assert {item["account_id"] for item in schedule_items} == {ids["allowed_account"]}

    outbox = client.get(
        "/api/v1/outbox",
        headers={"x-session-token": operator_token},
    )
    assert outbox.status_code == 200
    assert {item["account_id"] for item in outbox.json()["items"]} == {
        ids["allowed_account"]
    }
    assert (
        client.get(
            "/api/v1/outbox",
            headers={"x-session-token": viewer_token},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/schedule/{foreign.json()['id']}",
            headers={"x-session-token": operator_token},
        ).status_code
        == 404
    )

    broadcast_disabled = client.post(
        "/api/v1/broadcast",
        headers={"x-session-token": admin_token},
        json={"targets": [ids["allowed_conversation"]], "message": "disabled"},
    )
    assert broadcast_disabled.status_code == 503
    assert broadcast_disabled.json()["detail"]["code"] == "broadcast_disabled"

    app.state.runtime.web_settings.setdefault("plugins", {})["broadcast"] = True
    assert (
        client.post(
            "/api/v1/broadcast",
            headers={"x-session-token": operator_token},
            json={"targets": [ids["allowed_conversation"]], "message": "forbidden"},
        ).status_code
        == 403
    )


def test_viewer_reads_only_allowed_objects_and_cannot_mutate_them(security_api):
    client, _, factory = security_api
    ids = _seed_conversations(factory)
    admin_token = _login(client)
    viewer_token = _register_user(
        client,
        admin_token,
        username="object-viewer",
        role="viewer",
        account_ids=[ids["allowed_account"]],
    )
    headers = {"x-session-token": viewer_token}

    own_messages = client.get(
        f"/api/v1/conversations/{ids['allowed_conversation']}/messages",
        headers=headers,
    )
    assert own_messages.status_code == 200
    assert {item["message_id"] for item in own_messages.json()["messages"]} == {
        ids["allowed_message"]
    }
    assert (
        client.get(
            f"/api/v1/conversations/{ids['foreign_conversation']}/messages",
            headers=headers,
        ).status_code
        == 404
    )

    assert (
        client.get(
            f"/api/v1/contacts/{ids['allowed_contact']}/settings",
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/contacts/{ids['foreign_contact']}/settings",
            headers=headers,
        ).status_code
        == 404
    )

    conversations = client.get("/api/v1/conversations", headers=headers).json()
    contacts = client.get("/api/v1/contacts", headers=headers).json()
    assert {item["id"] for item in conversations["available_accounts"]} == {
        ids["allowed_account"]
    }
    assert {item["id"] for item in contacts["available_accounts"]} == {
        ids["allowed_account"]
    }

    forbidden_writes = [
        client.post(
            f"/api/v1/contacts/{ids['allowed_contact']}/conversation",
            headers=headers,
        ),
        client.patch(
            f"/api/v1/conversations/{ids['allowed_conversation']}/auto-reply",
            headers=headers,
            json={"enabled": True},
        ),
        client.patch(
            f"/api/v1/conversations/{ids['allowed_conversation']}",
            headers=headers,
            json={"pinned": True},
        ),
        client.post(
            f"/api/v1/conversations/{ids['allowed_conversation']}/read",
            headers=headers,
        ),
        client.delete(
            f"/api/v1/conversations/{ids['allowed_conversation']}",
            headers=headers,
        ),
        client.post(
            f"/api/v1/conversations/{ids['allowed_conversation']}/reply",
            headers=headers,
            json={"message": "viewer must not send"},
        ),
        client.post(
            f"/api/v1/conversations/{ids['allowed_conversation']}/translations",
            headers=headers,
            json={"anchor_message_id": ids["allowed_message"]},
        ),
        client.post(
            f"/api/v1/conversations/{ids['allowed_conversation']}/translate",
            headers=headers,
            json={"content": "viewer must not translate"},
        ),
        client.put(
            f"/api/v1/contacts/{ids['allowed_contact']}/settings",
            headers=headers,
            json={"notes": "viewer must not edit"},
        ),
        client.post(
            f"/api/v1/messages/{ids['allowed_message']}/translate",
            headers=headers,
            json={"content": "允许账号消息"},
        ),
    ]
    assert {response.status_code for response in forbidden_writes} == {403}


def test_operator_object_access_is_limited_to_assigned_accounts(security_api):
    client, _, factory = security_api
    ids = _seed_conversations(factory)
    admin_token = _login(client)
    operator_token = _register_user(
        client,
        admin_token,
        username="object-operator",
        role="operator",
        account_ids=[ids["allowed_account"]],
    )
    headers = {"x-session-token": operator_token}

    foreign_requests = [
        client.get(
            f"/api/v1/conversations/{ids['foreign_conversation']}/messages",
            headers=headers,
        ),
        client.post(
            f"/api/v1/contacts/{ids['foreign_contact']}/conversation",
            headers=headers,
        ),
        client.patch(
            f"/api/v1/conversations/{ids['foreign_conversation']}/auto-reply",
            headers=headers,
            json={"enabled": True},
        ),
        client.patch(
            f"/api/v1/conversations/{ids['foreign_conversation']}",
            headers=headers,
            json={"pinned": True},
        ),
        client.post(
            f"/api/v1/conversations/{ids['foreign_conversation']}/read",
            headers=headers,
        ),
        client.delete(
            f"/api/v1/conversations/{ids['foreign_conversation']}",
            headers=headers,
        ),
        client.post(
            f"/api/v1/conversations/{ids['foreign_conversation']}/reply",
            headers=headers,
            json={"message": "cross-account send"},
        ),
        client.post(
            f"/api/v1/conversations/{ids['foreign_conversation']}/translations",
            headers=headers,
            json={"anchor_message_id": ids["foreign_message"]},
        ),
        client.post(
            f"/api/v1/conversations/{ids['foreign_conversation']}/translate",
            headers=headers,
            json={"content": "cross-account translation"},
        ),
        client.get(
            f"/api/v1/contacts/{ids['foreign_contact']}/settings",
            headers=headers,
        ),
        client.put(
            f"/api/v1/contacts/{ids['foreign_contact']}/settings",
            headers=headers,
            json={"notes": "cross-account edit"},
        ),
        client.post(
            f"/api/v1/messages/{ids['foreign_message']}/translate",
            headers=headers,
            json={"content": "其他账号消息"},
        ),
    ]
    assert {response.status_code for response in foreign_requests} == {404}

    assert (
        client.post(
            f"/api/v1/contacts/{ids['allowed_contact']}/conversation",
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/v1/contacts/{ids['allowed_contact']}/settings",
            headers=headers,
            json={"notes": "operator update"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/conversations/{ids['allowed_conversation']}/auto-reply",
            headers=headers,
            json={"enabled": True},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/conversations/{ids['allowed_conversation']}",
            headers=headers,
            json={"pinned": True},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/conversations/{ids['allowed_conversation']}/read",
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/conversations/{ids['allowed_conversation']}/reply",
            headers=headers,
            json={"message": "operator reply"},
        ).status_code
        == 202
    )
    assert (
        client.post(
            f"/api/v1/conversations/{ids['allowed_conversation']}/translations",
            headers=headers,
            json={"anchor_message_id": ids["allowed_message"]},
        ).status_code
        == 202
    )
    assert (
        client.post(
            f"/api/v1/conversations/{ids['allowed_conversation']}/translate",
            headers=headers,
            json={"content": "已经是中文"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/messages/{ids['allowed_message']}/translate",
            headers=headers,
            json={"content": "允许账号消息"},
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/conversations/{ids['allowed_conversation']}",
            headers=headers,
        ).status_code
        == 200
    )


def test_translation_uses_stored_message_and_rejects_cache_poisoning(security_api):
    client, _, factory = security_api
    ids = _seed_conversations(factory)
    admin_token = _login(client)
    with factory() as session:
        message = Message(
            account_id=ids["allowed_account"],
            conversation_id=ids["allowed_conversation"],
            direction="inbound",
            message_type="text",
            content="数据库原文",
            status="received",
        )
        session.add(message)
        session.commit()
        message_id = message.id

    poisoned = client.post(
        f"/api/v1/messages/{message_id}/translate",
        headers={"x-session-token": admin_token},
        json={"content": "attacker controlled text"},
    )
    assert poisoned.status_code == 409
    assert poisoned.json()["detail"]["code"] == "source_content_mismatch"
    with factory() as session:
        assert session.scalar(select(MessageTranslation)) is None

    translated = client.post(
        f"/api/v1/messages/{message_id}/translate",
        headers={"x-session-token": admin_token},
        json={},
    )
    assert translated.status_code == 200
    assert translated.json()["lang"] == "Chinese"
    with factory() as session:
        row = session.scalar(select(MessageTranslation))
        assert row is not None
        assert row.message_id == message_id
        assert row.source_text == "数据库原文"


def test_authz_fails_closed_for_expired_sessions_and_unknown_roles(security_api):
    client, app, factory = security_api
    ids = _seed_conversations(factory)
    runtime = app.state.runtime
    runtime.web_settings.setdefault("sessions", {}).update(
        {
            "expired-token": {
                "username": "admin",
                "expires_at": time.time() - 60,
            },
            "unknown-role-token": {
                "username": "misconfigured-user",
                "expires_at": time.time() + 3600,
            },
        }
    )
    runtime.web_settings.setdefault("users", {})["misconfigured-user"] = {
        "role": "owner",
        "allowed_account_ids": [ids["allowed_account"]],
    }

    assert (
        client.get(
            "/api/v1/conversations",
            headers={"x-session-token": "expired-token"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/conversations",
            headers={"x-session-token": "unknown-role-token"},
        ).status_code
        == 403
    )


def test_conversation_list_does_not_join_a_contact_from_another_account(
    security_api,
):
    client, _, factory = security_api
    ids = _seed_conversations(factory)
    admin_token = _login(client)
    viewer_token = _register_user(
        client,
        admin_token,
        username="bad-relation-viewer",
        role="viewer",
        account_ids=[ids["allowed_account"]],
    )
    with factory() as session:
        conversation = session.get(Conversation, ids["allowed_conversation"])
        conversation.contact_id = ids["foreign_contact"]
        session.commit()

    response = client.get(
        "/api/v1/conversations",
        headers={"x-session-token": viewer_token},
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["conversation_id"] == ids["allowed_conversation"]
    assert item["user_name"] != "Foreign"
    assert item["contact_profile"] == {
        "remark": None,
        "notes": None,
        "tags": [],
        "language": None,
    }


def test_compat_standalone_builder_exposes_runtime_to_v1_routers(
    security_api,
    tmp_path: Path,
):
    _, _, factory = security_api
    app = build_compat_app(
        runtime_mode="standalone",
        runtime_dir=tmp_path / "compat-runtime",
        account_session_factory=factory,
        account_bridge=_FakeBridge(),
        internal_event_token="security-test-token",
        account_reconcile_interval_seconds=3600,
    )

    assert app.state.runtime_mode == "standalone"
    assert app.state.runtime.internal_event_token == "security-test-token"


def test_legacy_session_without_username_is_not_promoted_to_admin(security_api):
    client, app, _ = security_api
    app.state.runtime.web_settings.setdefault("sessions", {})["legacy-token"] = {
        "issued_at": time.time(),
        "expires_at": time.time() + 3600,
    }

    response = client.get(
        "/api/v1/users",
        headers={"x-session-token": "legacy-token"},
    )

    assert response.status_code == 401


def test_changing_ai_base_url_requires_a_new_key_in_the_same_request(security_api):
    client, _, _ = security_api
    admin_token = _login(client)

    rejected = client.put(
        "/api/v1/ai/settings",
        headers={"x-session-token": admin_token},
        json={"base_url": "https://8.8.8.8/v1"},
    )
    accepted = client.put(
        "/api/v1/ai/settings",
        headers={"x-session-token": admin_token},
        json={"base_url": "https://8.8.8.8/v1", "api_key": "replacement-key"},
    )

    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "api_key_required_for_base_url_change"
    assert accepted.status_code == 200


def test_non_admin_users_receive_only_minimal_runtime_capabilities(security_api):
    client, _, _ = security_api
    admin_token = _login(client)
    viewer_token = _register_user(
        client,
        admin_token,
        username="capabilities-viewer",
        role="viewer",
    )

    assert (
        client.get(
            "/api/v1/settings",
            headers={"x-session-token": viewer_token},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/ai/settings",
            headers={"x-session-token": viewer_token},
        ).status_code
        == 403
    )

    capabilities = client.get(
        "/api/v1/capabilities",
        headers={"x-session-token": viewer_token},
    )
    assert capabilities.status_code == 200
    payload = capabilities.json()
    assert set(payload) == {
        "runtime_mode",
        "message_ops",
        "reply",
        "plugins",
        "auto_translate",
    }
    serialized = str(payload).lower()
    for forbidden in ("base_url", "api_key", "hint", "channels", "aliases"):
        assert forbidden not in serialized
