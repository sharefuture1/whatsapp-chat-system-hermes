from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from whatsapp_chat_system.db import Base
from whatsapp_chat_system.db import models
from whatsapp_chat_system.standalone_api import build_standalone_app
from whatsapp_chat_system.standalone_api import _current_alembic_head

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
        ddl = "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        connection.execute(text(ddl))
        insert_revision = "INSERT INTO alembic_version (version_num) VALUES (:revision)"
        connection.execute(
            text(insert_revision),
            {"revision": _current_alembic_head()},
        )
        account = models.WhatsAppAccount.__table__.insert().values(
            id="acc-1",
            name="WA1",
            status="online",
            enabled=True,
            session_ref="account:acc-1",
            is_primary=True,
        )
        connection.execute(account)
    engine.dispose()
    app = build_standalone_app(runtime_dir=tmp_path / "runtime")
    return app, database


def _login(client: TestClient) -> dict[str, str]:
    response = client.post("/api/login", json={"password": PASSWORD})
    assert response.status_code == 200
    token = response.json()["session_token"]
    return {"x-session-token": token}


def _event(event_id: str, message_id: str, body: str, sequence: int) -> dict:
    payload = {
        "schema_version": 1,
        "wa_message_id": message_id,
        "remote_jid": "85620@s.whatsapp.net",
        "sender_jid": "85620@s.whatsapp.net",
        "participant_jid": None,
        "from_me": False,
        "conversation_type": "dm",
        "message_type": "text",
        "timestamp": "2026-10-03T12:00:00Z",
        "text": body,
        "push_name": "Customer",
        "quoted_wa_message_id": None,
        "media": None,
    }
    return {
        "event_id": event_id,
        "event_type": "message.upsert",
        "account_id": "acc-1",
        "occurred_at": "2026-10-03T12:00:00Z",
        "sequence": sequence,
        "payload": payload,
    }


def _post_event(client: TestClient, body: dict):
    headers = {"X-Internal-Token": TOKEN}
    return client.post("/internal/events/whatsapp", json=body, headers=headers)


def _ids(database: Path) -> tuple[str, str]:
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            conversation_id = connection.scalar(select(models.Conversation.id).limit(1))
            message_id = connection.scalar(select(models.Message.id).limit(1))
    finally:
        engine.dispose()
    assert conversation_id is not None
    assert message_id is not None
    return conversation_id, message_id


def _batch_exists(database: Path) -> bool:
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            batch_id = connection.scalar(select(models.TranslationBatch.id).limit(1))
    finally:
        engine.dispose()
    return batch_id is not None


def test_auto_translate_switch_controls_runtime(tmp_path: Path):
    app, database = _app(tmp_path)
    with TestClient(app) as client:
        headers = _login(client)
        body = {"plugin_id": "auto_translate", "enabled": False}
        disabled = client.post("/api/v1/plugins/toggle", json=body, headers=headers)
        assert disabled.status_code == 200

        event = _event("evt-1", "wa-1", "สวัสดีครับ", 1)
        assert _post_event(client, event).status_code == 200
        assert _batch_exists(database) is False

        conversation_id, message_id = _ids(database)
        path = f"/api/v1/conversations/{conversation_id}/translations"
        request = {
            "anchor_message_id": message_id,
            "target_lang": "zh-CN",
            "window_size": 10,
        }
        manual = client.post(path, json=request, headers=headers)
        assert manual.status_code == 409
        assert manual.json()["detail"]["code"] == "plugin_disabled"

        path = f"/api/v1/conversations/{conversation_id}/reply"
        request = {"message": "hello", "mode": "translate", "preview_only": True}
        preview = client.post(path, json=request, headers=headers)
        assert preview.status_code == 409
        assert preview.json()["detail"]["code"] == "plugin_disabled"

        body = {"plugin_id": "auto_translate", "enabled": True}
        enabled = client.post("/api/v1/plugins/toggle", json=body, headers=headers)
        assert enabled.status_code == 200
        event = _event("evt-2", "wa-2", "ขอสอบถามราคา", 2)
        assert _post_event(client, event).status_code == 200
        assert _batch_exists(database) is True


def test_quick_reply_switch_controls_preview(tmp_path: Path):
    app, database = _app(tmp_path)
    with TestClient(app) as client:
        headers = _login(client)
        event = _event("evt-preview", "wa-preview", "hello", 1)
        assert _post_event(client, event).status_code == 200
        conversation_id, _ = _ids(database)

        body = {"plugin_id": "quick_reply", "enabled": False}
        disabled = client.post("/api/v1/plugins/toggle", json=body, headers=headers)
        assert disabled.status_code == 200

        path = f"/api/v1/conversations/{conversation_id}/reply"
        request = {"message": "你好", "mode": "smart", "preview_only": True}
        smart = client.post(path, json=request, headers=headers)
        assert smart.status_code == 409
        assert smart.json()["detail"]["code"] == "plugin_disabled"

        request = {"message": "你好", "mode": "direct", "preview_only": True}
        direct = client.post(path, json=request, headers=headers)
        assert direct.status_code == 202
        assert direct.json()["success"] is True
        assert direct.json()["mode"] == "direct"


def test_persona_switch_controls_catalog_and_assignment(tmp_path: Path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        headers = _login(client)
        body = {"plugin_id": "persona_styles", "enabled": False}
        disabled = client.post("/api/v1/plugins/toggle", json=body, headers=headers)
        assert disabled.status_code == 200

        catalog = client.get("/api/v1/personas", headers=headers)
        assert catalog.status_code == 200
        assert catalog.json()["plugin_enabled"] is False
        items = catalog.json()["items"]
        assert all(item["available"] is False for item in items)

        path = "/api/v1/contacts/85620@s.whatsapp.net/persona"
        assign = client.put(
            path,
            json={"persona_id": "mature-uncle"},
            headers=headers,
        )
        assert assign.status_code == 409
        assert assign.json()["detail"]["code"] == "plugin_disabled"

        clear = client.put(
            path,
            json={"persona_id": "default"},
            headers=headers,
        )
        assert clear.status_code == 200
