from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from conftest import create_profile
from whatsapp_chat_system.db.base import Base
from whatsapp_chat_system.db.models import (
    Contact,
    Conversation,
    Message,
    WhatsAppAccount,
    WhatsAppEvent,
)
from whatsapp_chat_system.events.whatsapp import WhatsAppEventEnvelope, canonical_hash
from whatsapp_chat_system.web_api import build_app


TOKEN = "internal-test-secret"


@pytest.fixture
def events_api(tmp_path):
    database = tmp_path / "events.db"
    engine = create_engine(
        f"sqlite:///{database}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    profile = create_profile(tmp_path / "profile")
    with factory() as db:
        db.add_all(
            [
                WhatsAppAccount(
                    id="account-a", name="A", session_ref="account:account-a"
                ),
                WhatsAppAccount(
                    id="account-b", name="B", session_ref="account:account-b"
                ),
            ]
        )
        db.commit()
    client = TestClient(
        build_app(
            str(profile), account_session_factory=factory, internal_event_token=TOKEN
        )
    )
    yield client, factory
    engine.dispose()


def envelope(
    event_id="evt-1",
    event_type="message.upsert",
    account_id="account-a",
    sequence=1,
    payload=None,
):
    if payload is None:
        payload = message_payload()
    return {
        "event_id": event_id,
        "event_type": event_type,
        "account_id": account_id,
        "occurred_at": "2026-07-10T00:00:00Z",
        "sequence": sequence,
        "payload": payload,
    }


def message_payload(**changes):
    payload = {
        "schema_version": 1,
        "wa_message_id": "WA-1",
        "remote_jid": "85620@s.whatsapp.net",
        "sender_jid": "85620@s.whatsapp.net",
        "participant_jid": None,
        "from_me": False,
        "conversation_type": "dm",
        "message_type": "text",
        "timestamp": "2026-07-10T00:00:00Z",
        "text": "hello",
        "push_name": "Customer",
        "quoted_wa_message_id": None,
        "media": None,
    }
    payload.update(changes)
    return payload


def post(client, body, token=TOKEN, request_id=None):
    headers = {"X-Internal-Token": token}
    if request_id:
        headers["X-Request-ID"] = request_id
    return client.post("/internal/events/whatsapp", json=body, headers=headers)


def test_lid_contact_uses_push_name_instead_of_lid(events_api):
    client, factory = events_api
    response = post(client, envelope(payload=message_payload(
        remote_jid="12345@lid",
        sender_jid="12345@lid",
        push_name="小明",
    )))
    assert response.status_code in {200, 202}
    with factory() as db:
        contact = db.scalar(select(Contact).where(Contact.remote_jid == "12345@lid"))
        conversation = db.scalar(select(Conversation).where(Conversation.remote_jid == "12345@lid"))
        assert contact.display_name == "小明"
        assert conversation.title == "小明"


def test_lid_contact_without_name_uses_human_fallback(events_api):
    client, factory = events_api
    response = post(client, envelope(payload=message_payload(
        remote_jid="67890@lid",
        sender_jid="67890@lid",
        push_name=None,
    )))
    assert response.status_code in {200, 202}
    with factory() as db:
        conversation = db.scalar(select(Conversation).where(Conversation.remote_jid == "67890@lid"))
        assert conversation.title == "WhatsApp 联系人"


def test_internal_token_is_fail_closed_and_does_not_use_web_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'closed.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    profile = create_profile(tmp_path / "profile")
    client = TestClient(
        build_app(
            str(profile), account_session_factory=factory, internal_event_token=""
        )
    )

    response = client.post(
        "/internal/events/whatsapp",
        json=envelope(),
        headers={
            "X-Internal-Token": TOKEN,
            "x-session-token": "irrelevant",
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "internal_events_not_configured"

    configured = TestClient(
        build_app(
            str(profile), account_session_factory=factory, internal_event_token=TOKEN
        )
    )
    assert post(configured, envelope(), token="wrong").status_code == 401
    engine.dispose()


def test_request_id_is_echoed_or_generated_and_errors_are_structured(events_api):
    client, _ = events_api
    response = post(client, envelope(), request_id="req-fixed")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-fixed"

    invalid = post(client, {**envelope(event_id="evt-invalid"), "unexpected": True})
    assert invalid.status_code == 422
    assert invalid.headers["X-Request-ID"]
    assert invalid.json()["error"]["code"] == "validation_error"
    assert invalid.json()["error"]["request_id"] == invalid.headers["X-Request-ID"]


def test_duplicate_hash_and_identity_conflict(events_api):
    client, factory = events_api
    first = post(client, envelope())
    duplicate = post(client, envelope())
    conflict = post(client, envelope(payload=message_payload(text="changed")))

    assert first.json()["duplicate"] is False
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "event_identity_conflict"
    with factory() as db:
        assert len(db.scalars(select(WhatsAppEvent)).all()) == 1


def test_unknown_account_is_retryable_and_leaves_no_event(events_api):
    client, factory = events_api
    response = post(client, envelope(account_id="missing"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"
    assert response.json()["error"]["retryable"] is True
    with factory() as db:
        assert db.scalar(select(WhatsAppEvent)) is None


def test_message_upsert_is_atomic_scoped_and_duplicate_does_not_increment_unread(
    events_api,
):
    client, factory = events_api
    assert post(client, envelope()).status_code == 200
    assert post(client, envelope()).json()["duplicate"] is True

    with factory() as db:
        contact = db.scalar(select(Contact).where(Contact.account_id == "account-a"))
        conversation = db.scalar(
            select(Conversation).where(Conversation.account_id == "account-a")
        )
        message = db.scalar(select(Message).where(Message.account_id == "account-a"))
        event = db.scalar(select(WhatsAppEvent))
        assert contact.remote_jid == "85620@s.whatsapp.net"
        assert conversation.contact_id == contact.id
        assert conversation.unread_count == 1
        assert message.conversation_id == conversation.id
        assert message.contact_id == contact.id
        assert message.direction == "inbound"
        assert message.occurred_at == datetime(
            2026, 7, 10, tzinfo=timezone.utc
        ).replace(tzinfo=None)
        assert message.received_at is not None
        assert event.status == "processed"


def test_same_wa_message_id_is_independent_per_account_and_a_cannot_update_b(
    events_api,
):
    client, factory = events_api
    assert (
        post(client, envelope(event_id="a", account_id="account-a")).status_code == 200
    )
    assert (
        post(client, envelope(event_id="b", account_id="account-b")).status_code == 200
    )
    assert (
        post(
            client,
            envelope(
                event_id="a-later",
                account_id="account-a",
                sequence=2,
                payload=message_payload(text="A changed"),
            ),
        ).status_code
        == 200
    )

    with factory() as db:
        messages = db.scalars(select(Message).order_by(Message.account_id)).all()
        assert [(m.account_id, m.content) for m in messages] == [
            ("account-a", "A changed"),
            ("account-b", "hello"),
        ]


def test_v1_conversations_are_visible_and_scoped_by_account(events_api):
    client, _ = events_api
    assert (
        post(client, envelope(event_id="a", account_id="account-a")).status_code == 200
    )
    assert (
        post(
            client,
            envelope(
                event_id="b",
                account_id="account-b",
                payload=message_payload(
                    wa_message_id="WA-B",
                    remote_jid="85621@s.whatsapp.net",
                    sender_jid="85621@s.whatsapp.net",
                    push_name="Second account customer",
                    text="second account message",
                ),
            ),
        ).status_code
        == 200
    )

    login = client.post("/api/login", json={"password": "test-pass"})
    client.headers.update({"x-session-token": login.json()["session_token"]})

    account_b = client.get("/api/v1/conversations?account_id=account-b&limit=50")
    assert account_b.status_code == 200
    assert account_b.json()["total"] == 1
    assert account_b.json()["available_platforms"] == ["whatsapp"]
    assert [account["name"] for account in account_b.json()["available_accounts"]] == [
        "B"
    ]
    item = account_b.json()["items"][0]
    assert item["account_id"] == "account-b"
    assert item["user_name"] == "Second account customer"
    assert item["last_message"] == "second account message"

    messages = client.get(
        f"/api/v1/conversations/{item['conversation_id']}/messages?limit=50"
    )
    assert messages.status_code == 200
    assert messages.json()["account_id"] == "account-b"
    assert [message["content"] for message in messages.json()["messages"]] == [
        "second account message"
    ]

    all_accounts = client.get(
        "/api/v1/conversations?platform=whatsapp&account_id=all&limit=50"
    )
    assert all_accounts.status_code == 200
    assert all_accounts.json()["total"] == 2
    assert {account["id"] for account in all_accounts.json()["available_accounts"]} == {
        "account-a",
        "account-b",
    }

    contacts = client.get("/api/v1/contacts?platform=whatsapp&account_id=all&limit=50")
    assert contacts.status_code == 200
    assert contacts.json()["total"] == 2
    assert {
        (item["account_id"], item["remote_jid"]) for item in contacts.json()["items"]
    } == {
        ("account-a", "85620@s.whatsapp.net"),
        ("account-b", "85621@s.whatsapp.net"),
    }
    second = next(
        item for item in contacts.json()["items"] if item["account_id"] == "account-b"
    )
    assert second["account_name"] == "B"
    assert second["platform"] == "whatsapp"
    assert second["conversation_id"] == item["conversation_id"]


def test_v1_conversation_prefers_contact_name_and_only_then_chat_title(events_api):
    client, factory = events_api
    contacts = {
        "schema_version": 1,
        "items": [{"remote_jid": "person@lid", "display_name": "WhatsApp 原始名称"}],
    }
    chats = {
        "schema_version": 1,
        "items": [
            {
                "remote_jid": "person@lid",
                "conversation_type": "dm",
                "title": "错误的聊天标题",
                "last_message_at": None,
                "last_message_preview": None,
            }
        ],
    }
    assert (
        post(
            client, envelope("name-contact", "contacts.upsert", payload=contacts)
        ).status_code
        == 200
    )
    assert (
        post(
            client, envelope("name-chat", "chats.upsert", sequence=2, payload=chats)
        ).status_code
        == 200
    )
    login = client.post("/api/login", json={"password": "test-pass"})
    client.headers.update({"x-session-token": login.json()["session_token"]})

    response = client.get("/api/v1/conversations?account_id=account-a")
    assert response.status_code == 200
    assert response.json()["items"][0]["user_name"] == "WhatsApp 原始名称"

    with factory() as db:
        contact = db.scalar(select(Contact).where(Contact.remote_jid == "person@lid"))
        contact.remark = "人工备注名"
        db.commit()
    assert (
        client.get("/api/v1/conversations?account_id=account-a").json()["items"][0][
            "user_name"
        ]
        == "人工备注名"
    )


def test_preview_does_not_go_backwards_and_outbound_does_not_add_unread(events_api):
    client, factory = events_api
    newer = message_payload(
        wa_message_id="new", timestamp="2026-07-10T02:00:00Z", text="new"
    )
    older = message_payload(
        wa_message_id="old", timestamp="2026-07-10T01:00:00Z", text="old"
    )
    outbound = message_payload(
        wa_message_id="out", timestamp="2026-07-10T03:00:00Z", text="out", from_me=True
    )
    post(client, envelope(event_id="new", sequence=1, payload=newer))
    post(client, envelope(event_id="old", sequence=2, payload=older))
    post(client, envelope(event_id="out", sequence=3, payload=outbound))

    with factory() as db:
        conversation = db.scalar(
            select(Conversation).where(Conversation.account_id == "account-a")
        )
        assert conversation.last_message_preview == "out"
        assert conversation.unread_count == 2


def test_contact_chat_history_batches_preserve_manual_fields_and_group_boundary(
    events_api,
):
    client, factory = events_api
    contacts = {
        "schema_version": 1,
        "items": [
            {
                "remote_jid": "person@lid",
                "display_name": "Remote",
                "phone_number": None,
                "lid": "person@lid",
                "avatar_url": None,
            }
        ],
    }
    assert (
        post(
            client, envelope("contacts-1", "contacts.upsert", payload=contacts)
        ).status_code
        == 200
    )
    with factory() as db:
        contact = db.scalar(select(Contact).where(Contact.remote_jid == "person@lid"))
        contact.remark, contact.tags, contact.notes, contact.language = (
            "Mine",
            ["vip"],
            "note",
            "lo",
        )
        db.commit()
    update = {
        "schema_version": 1,
        "items": [{"remote_jid": "person@lid", "display_name": "New"}],
    }
    assert (
        post(
            client,
            envelope("contacts-2", "contacts.update", sequence=2, payload=update),
        ).status_code
        == 200
    )
    chats = {
        "schema_version": 1,
        "items": [
            {
                "remote_jid": "group@g.us",
                "conversation_type": "group",
                "title": "G",
                "last_message_at": None,
                "last_message_preview": None,
            }
        ],
    }
    assert (
        post(
            client, envelope("chats-1", "chats.upsert", sequence=3, payload=chats)
        ).status_code
        == 200
    )
    history = {
        "schema_version": 1,
        "items": [
            message_payload(
                wa_message_id="hist-1",
                remote_jid="person@lid",
                sender_jid="person@lid",
                timestamp="2026-07-09T00:00:00Z",
                text="history",
            )
        ],
    }
    assert (
        post(
            client,
            envelope("hist-1", "history.messages.upsert", sequence=4, payload=history),
        ).status_code
        == 200
    )
    assert (
        post(
            client,
            envelope("hist-2", "history.messages.upsert", sequence=5, payload=history),
        ).status_code
        == 200
    )
    with factory() as db:
        contact = db.scalar(select(Contact).where(Contact.remote_jid == "person@lid"))
        assert (
            contact.display_name,
            contact.remark,
            contact.tags,
            contact.notes,
            contact.language,
        ) == ("New", "Mine", ["vip"], "note", "lo")
        assert (
            db.scalar(select(Contact).where(Contact.remote_jid == "group@g.us")) is None
        )
        assert (
            db.scalar(
                select(Conversation).where(Conversation.remote_jid == "group@g.us")
            ).type
            == "group"
        )
        assert (
            db.scalar(
                select(Conversation).where(Conversation.remote_jid == "person@lid")
            ).unread_count
            == 0
        )


def test_chat_unread_is_authoritative_when_present_and_partial_update_preserves_it(
    events_api,
):
    client, factory = events_api
    full = {
        "schema_version": 1,
        "items": [
            {
                "remote_jid": "person@lid",
                "conversation_type": "dm",
                "title": "P",
                "last_message_at": None,
                "last_message_preview": None,
                "unread_count": 7,
            }
        ],
    }
    partial = {
        "schema_version": 1,
        "items": [
            {"remote_jid": "person@lid", "conversation_type": "dm", "title": "Renamed"}
        ],
    }
    assert (
        post(client, envelope("chat-full", "chats.upsert", payload=full)).status_code
        == 200
    )
    assert (
        post(
            client,
            envelope("chat-partial", "chats.update", sequence=2, payload=partial),
        ).status_code
        == 200
    )
    with factory() as db:
        conversation = db.scalar(
            select(Conversation).where(Conversation.remote_jid == "person@lid")
        )
        assert conversation.unread_count == 7


def test_conversation_messages_returns_latest_limit_in_ascending_order(events_api):
    client, _ = events_api
    for index in range(5):
        payload = message_payload(
            wa_message_id=f"m-{index}",
            text=str(index),
            timestamp=f"2026-07-10T00:0{index}:00Z",
        )
        assert (
            post(
                client, envelope(f"e-{index}", sequence=index + 1, payload=payload)
            ).status_code
            == 200
        )
    login = client.post("/api/login", json={"password": "test-pass"})
    client.headers.update({"x-session-token": login.json()["session_token"]})
    conversation_id = client.get("/api/v1/conversations").json()["items"][0][
        "conversation_id"
    ]
    response = client.get(f"/api/v1/conversations/{conversation_id}/messages?limit=3")
    assert [item["content"] for item in response.json()["messages"]] == ["2", "3", "4"]


def test_account_status_sequence_is_monotonic_and_qr_raw_is_not_persisted(events_api):
    client, factory = events_api
    qr = envelope(
        "qr",
        "account.qr",
        sequence=10,
        payload={"qr": "SECRET-QR-RAW", "expires_at": "2026-07-10T00:01:00Z"},
    )
    assert post(client, qr).status_code == 200
    assert (
        post(
            client,
            envelope(
                "late",
                "account.connected",
                sequence=9,
                payload={"phone_number": "+85620"},
            ),
        ).status_code
        == 200
    )

    with factory() as db:
        account = db.get(WhatsAppAccount, "account-a")
        events = db.scalars(
            select(WhatsAppEvent).order_by(WhatsAppEvent.sequence)
        ).all()
        assert account.status == "qr_pending"
        assert account.last_event_sequence == 10
        assert all("SECRET-QR-RAW" not in str(event.payload) for event in events)
        assert all(event.status == "processed" for event in events)


def test_receipts_are_monotonic_failed_does_not_override_and_unknown_is_retryable(
    events_api,
):
    client, factory = events_api
    post(client, envelope(event_id="upsert", payload=message_payload(from_me=True)))
    for seq, kind in [
        (2, "message.delivered"),
        (3, "message.sent"),
        (4, "message.read"),
        (5, "message.failed"),
    ]:
        response = post(
            client,
            envelope(
                event_id=kind,
                event_type=kind,
                sequence=seq,
                payload={
                    "wa_message_id": "WA-1",
                    "timestamp": f"2026-07-10T00:0{seq}:00Z",
                    "error_code": "x" if kind == "message.failed" else None,
                    "error_message": "failed" if kind == "message.failed" else None,
                },
            ),
        )
        assert response.status_code == 200

    unknown = post(
        client,
        envelope(
            event_id="unknown",
            event_type="message.read",
            sequence=6,
            payload={
                "wa_message_id": "missing",
                "timestamp": "2026-07-10T00:06:00Z",
                "error_code": None,
                "error_message": None,
            },
        ),
    )
    assert unknown.status_code == 409
    assert unknown.json()["error"]["code"] == "message_not_found"
    assert unknown.json()["error"]["retryable"] is True
    with factory() as db:
        message = db.scalar(select(Message).where(Message.wa_message_id == "WA-1"))
        assert message.status == "read"
        assert (
            db.scalar(select(WhatsAppEvent).where(WhatsAppEvent.event_id == "unknown"))
            is None
        )


def test_migrated_canonical_event_hash_is_duplicate_not_conflict(events_api):
    client, factory = events_api
    body = envelope(
        event_id="migrated",
        event_type="account.connected",
        sequence=0,
        payload={"state": "online"},
    )
    parsed = WhatsAppEventEnvelope.model_validate(body)
    with factory() as db:
        db.add(
            WhatsAppEvent(
                id="migrated-row",
                event_id="migrated",
                account_id="account-a",
                event_type="account.connected",
                occurred_at=parsed.occurred_at,
                sequence=0,
                payload={"state": "online"},
                payload_hash=canonical_hash(parsed),
                status="processed",
            )
        )
        db.commit()

    response = post(client, body)
    assert response.status_code == 200
    assert response.json()["duplicate"] is True
