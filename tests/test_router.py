from __future__ import annotations

import json
import sqlite3

from conftest import create_profile
from whatsapp_chat_system.config import AppConfig
from whatsapp_chat_system.rewriter import RewriteResult
from whatsapp_chat_system.router import AdminRouter


def test_admin_smart_send_passes_contact_persona_override_and_sidecar(
    monkeypatch, tmp_path
):
    profile = create_profile(tmp_path / "profile")
    target_id = "contact@lid"
    settings_path = profile / "web-settings.json"
    settings = json.loads(settings_path.read_text())
    settings["reply"]["user_overrides"] = {target_id: {"persona_id": "tong-jincheng"}}
    settings_path.write_text(json.dumps(settings))
    (profile / "channel_directory.json").write_text(
        json.dumps(
            {
                "platforms": {
                    "whatsapp": [{"id": target_id, "name": "Contact", "type": "dm"}]
                },
            }
        )
    )
    sidecar = {"preferred_language": "Thai", "tone": "warm"}
    (profile / "user-memory-md" / f"contact__{target_id}.json").write_text(
        json.dumps(sidecar)
    )

    config = AppConfig.from_profile(profile)
    admin_id = next(iter(config.admin_ids))
    with sqlite3.connect(profile / "state.db") as db:
        db.execute(
            "INSERT INTO sessions(id, user_id, title, started_at, source) VALUES (?, ?, ?, ?, ?)",
            ("admin-session", admin_id, "Admin", 0, "whatsapp"),
        )
        db.execute(
            "INSERT INTO messages(session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            ("admin-session", "user", "发给 Contact：你好", 1),
        )

    router = AdminRouter(config)
    captured: dict[str, object] = {}

    def capture_rewrite(target, message, memory_md, **kwargs):
        captured.update(kwargs)
        return RewriteResult(language="Thai", message="你好", used_fallback=False)

    monkeypatch.setattr(router.rewriter, "rewrite", capture_rewrite)
    monkeypatch.setattr(
        router,
        "send_prepared_reply",
        lambda *args, **kwargs: {"success": True, "stdout": "", "stderr": ""},
    )
    monkeypatch.setattr(router.messenger, "send_admin_text", lambda *args, **kwargs: [])

    assert router.run() == 0
    assert captured["sidecar"] == sidecar
    assert captured["reply_overrides"] == {"persona_id": "tong-jincheng"}
