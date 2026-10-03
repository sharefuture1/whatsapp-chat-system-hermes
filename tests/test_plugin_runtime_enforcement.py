from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from whatsapp_chat_system.db import Base
from whatsapp_chat_system.db import models as _models  # noqa: F401
from whatsapp_chat_system.db.models import (
    Conversation,
    Message,
    TranslationBatch,
    WhatsAppAccount,
)
from whatsapp_chat_system.standalone_api import (
    _current_alembic_head,
    build_standalone_app,
)

PASSWORD = "plugin-runtime-test-password"
TOKEN = "plugin-runtime-internal-token"


def _app(tmp_path: Path):
    database = tmp_path / "business.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{database}"
    os.environ["WHATSAPP_BRIDGE_INTERNAL_TOKEN"] = TOKEN
    os.environ["CHAT_SYSTEM_BOOTSTRAP_PASSWORD"] = PASSWORD
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": _current_alembic_head()},
        )
        connection.execute(
            WhatsAppAccount.__table__.insert().values(
                id="acc-1",
                name="WA1",
                status="online",
                enabled=True,
                session_ref="account:acc-1",
                is_primary=True,
            )
        )
    engine.dispose()
    return build_standalone_app(runtime_dir=tmp_path / "runtime"), database


def _login(client: TestClient) -> dict[str, str]:
    response = client.post("/api/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return {"x-session-token": response.json()["session_token"]}


def _event(event_id: str, wa_message_id: str, text_value: str, sequence: int) -> dict:
    return {
        "event_id": event_id,
        "event_type": "message.upsert",
        "account_id": "acc-1",
        "occurred_at": "2026-10-03T12:00:00Z",
        "sequence": sequence,
        "payload": {
            "schema_version": 1,
            "wa_message_id": wa_message_id,
            "remote_jid": "85620@s.whatsapp.net",
            "sender_jid": "85620@s.whatsapp.net",
            "participant_jid": None,
            "from_me": False,
            "conversation_type": "dm",
            "message_type": "text",
            "timestamp": "2026-10-03T12:00:00Z",
            "text": text_value,
            "push_name": "Customer",
            "quoted_wa_message_id": None,
            "media": None,
        },
    }


def _post_event(client: TestClient, body: dict):
    return client.post(
        "/internal/events/whatsapp",
        json=body,
        headers={"X-Internal-Token": TOKEN},
    )


def _conversation_and_message_ids(database: Path) -> tuple[str, str]:
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            conversation_id = connection.scalar(select(Conversation.id).limit(1))
            message_id = connection.scalar(select(Message.id).limit(1))
    finally:
        engine.dispose()
    assert conversation_id is not None
    assert message_id is not None
    return conversation_id, message_id


def test_auto_translate_plugin_off_stops_background_and_manual_translation(
    tmp_path: Path,
):
    app, database = _app(tmp_path)
    with TestClient(app) as client:
        headers = _login(client)
        disabled = client.post(
            "/api/v1/plugins/toggle",
            json={"plugin_id": "auto_translate", "enabled": False},
            headers=headers,
        )
        assert disabled.status_code == 200

        first = _post_event(client, _event("evt-1", "wa-1", "สวัสดีครับ", 1))
        assert first.status_code == 200

        engine = create_engine(f"sqlite:///{database}")
        try:
            with engine.connect() as connection:
                assert (
                    connection.scalar(select(TranslationBatch.id).limit(1)) is None
                )
        finally:
            engine.dispose()
        conversation_id, message_id = _conversation_and_message_ids(database)

        manual = client.post(
            f"/api/v1/conversations/{conversation_id}/translations",
            json={
                "anchor_message_id": message_id,
                "target_lang": "zh-CN",
                "window_size": 10,
            },
            headers=headers,
        )
        assert manual.status_code == 409
        assert manual.json()["detail"]["code"] == "plugin_disabled"

        enabled = client.post(
            "/api/v1/plugins/toggle",
            json={"plugin_id": "auto_translate", "enabled": True},
            headers=headers,
        )
        assert enabled.status_code == 200
        second = _post_event(client, _event("evt-2", "wa-2", "ขอสอบถามราคา", 2))
        assert second.status_code == 200

        engine = create_engine(f"sqlite:///{database}")
        try:
            with engine.connect() as connection:
                assert (
                    connection.scalar(select(TranslationBatch.id).limit(1)) is not None
                )
        finally:
            engine.dispose()


def test_quick_reply_plugin_off_blocks_ai_preview_but_direct_preview_stays_available(
    tmp_path: Path,
):
    app, database = _app(tmp_path)
    with TestClient(app) as client:
        headers = _login(client)
        assert (
            _post_event(
                client, _event("evt-preview", "wa-preview", "hello", 1)
            ).status_code
            == 200
        )
        conversation_id, _ = _conversation_and_message_ids(database)

        disabled = client.post(
            "/api/v1/plugins/toggle",
            json={"plugin_id": "quick_reply", "enabled": False},
            headers=headers,
        )
        assert disabled.status_code == 200

        smart = client.post(
            f"/api/v1/conversations/{conversation_id}/reply",
            json={"message": "你好", "mode": "smart", "preview_only": True},
            headers=headers,
        )
        assert smart.status_code == 409
        assert smart.json()["detail"]["code"] == "plugin_disabled"

        direct = client.post(
            f"/api/v1/conversations/{conversation_id}/reply",
            json={"message": "你好", "mode": "direct", "preview_only": True},
            headers=headers,
        )
        assert direct.status_code == 202
        assert direct.json()["success"] is True
        assert direct.json()["mode"] == "direct"


def test_persona_plugin_off_disables_catalog_use_and_assignment(tmp_path: Path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        headers = _login(client)
        disabled = client.post(
            "/api/v1/plugins/toggle",
            json={"plugin_id": "persona_styles", "enabled": False},
            headers=headers,
        )
        assert disabled.status_code == 200

        catalog = client.get("/api/v1/personas", headers=headers)
        assert catalog.status_code == 200
        assert catalog.json()["plugin_enabled"] is False
        assert all(item["available"] is False for item in catalog.json()["items"])

        assign = client.put(
            "/api/v1/contacts/85620@s.whatsapp.net/persona",
            json={"persona_id": "mature-uncle"},
            headers=headers,
        )
        assert assign.status_code == 409
        assert assign.json()["detail"]["code"] == "plugin_disabled"

        clear = client.put(
            "/api/v1/contacts/85620@s.whatsapp.net/persona",
            json={"persona_id": "default"},
            headers=headers,
        )
        assert clear.status_code == 200
