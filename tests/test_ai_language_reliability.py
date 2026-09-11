"""FR-AI-008/010/013/014: runtime settings, language and truthful translation."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_standalone_runtime import PASSWORD, standalone_app
from test_translations_dispatcher import (
    _FakeRewrite,
    _FakeWorker,
    _SessionTracker,
    _make_batch,
    _make_dispatcher,
    _seed,
    factory as _factory_fixture,
)
from whatsapp_chat_system.db.models import MessageTranslation, TranslationBatch
from whatsapp_chat_system.rewriter import Rewriter

factory = _factory_fixture


def test_ai_settings_save_refreshes_cached_rewriter_and_worker_manager(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("WENDING_AI_API_KEY", raising=False)
    app, _ = standalone_app(tmp_path, monkeypatch)
    manager = app.state.ai_settings_manager
    config = SimpleNamespace(
        paths=app.state.runtime.paths, ai_settings=app.state.runtime.ai_settings
    )
    rewriter = Rewriter(config, lambda *a, **kw: None, runtime_manager=manager)
    with TestClient(app) as client:
        token = client.post("/api/login", json={"password": PASSWORD}).json()[
            "session_token"
        ]
        response = client.put(
            "/api/v1/ai/settings",
            headers={"x-session-token": token},
            json={
                "api_key": "unit-test-runtime-secret",
                "default_model": "runtime-test-model",
            },
        )
        assert response.status_code == 200
        assert manager.effective_api_key == "unit-test-runtime-secret"
        assert rewriter.ai_service.resolve_model().model == "runtime-test-model"
        assert (
            rewriter.ai_service.resolve_model(contact_model="contact-model").model
            == "contact-model"
        )
        assert "unit-test-runtime-secret" not in response.text


@pytest.mark.parametrize("bad_output", ["", "hello"])
def test_empty_or_unchanged_translation_is_not_completed(factory, bad_output):
    anchor, messages, account_id, conversation_id = _seed(factory, ["hello"])
    batch_id = _make_batch(
        factory,
        anchor_id=anchor,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(
        tracker,
        batch_payload={
            "items": [
                {
                    "message_id": messages[0],
                    "source_lang": "English",
                    "zh": bad_output,
                }
            ]
        },
        fallback=lambda text, lang: _FakeRewrite(message=text),
    )
    assert _make_dispatcher(factory, tracker, worker).run_once() is True
    with factory() as session:
        row = session.scalar(select(MessageTranslation))
        assert row.status == "failed"
        assert session.get(TranslationBatch, batch_id).status == "failed"


def test_translation_requests_reuse_active_batch_and_reject_wrong_target(
    tmp_path, monkeypatch
):
    app, _ = standalone_app(tmp_path, monkeypatch)
    anchor, _, _, conversation_id = _seed(app.state.session_factory, ["hello"])
    # Do not run lifespan workers: the queued batch must remain pending.
    with TestClient(app) as client:
        client.portal.call(app.state.translation_dispatcher_task.cancel)
        token = client.post("/api/login", json={"password": PASSWORD}).json()[
            "session_token"
        ]
        client.headers["x-session-token"] = token
        path = f"/api/v1/conversations/{conversation_id}/translations"
        a = client.post(path, json={"anchor_message_id": anchor})
        b = client.post(path, json={"anchor_message_id": anchor})
        assert a.status_code == b.status_code == 202
        assert a.json()["batch_id"] == b.json()["batch_id"]
        state = client.get(f"{path}/{a.json()['batch_id']}")
        assert state.status_code == 200
        assert state.json()["status"] == "pending"
        invalid = client.post(
            path, json={"anchor_message_id": anchor, "target_lang": "en"}
        )
        assert invalid.status_code == 422


def test_whitespace_source_hash_is_stable_across_batches(factory):
    anchor, messages, account_id, conversation_id = _seed(factory, ["  hello  "])
    tracker = _SessionTracker(factory)
    worker = _FakeWorker(
        tracker,
        batch_payload={
            "items": [
                {
                    "message_id": messages[0],
                    "source_lang": "English",
                    "zh": "你好",
                }
            ]
        },
    )
    dispatcher = _make_dispatcher(factory, tracker, worker)
    for _ in range(2):
        _make_batch(
            factory,
            anchor_id=anchor,
            account_id=account_id,
            conversation_id=conversation_id,
        )
        dispatcher.run_once()
    assert tracker.ai_call_count == 1
