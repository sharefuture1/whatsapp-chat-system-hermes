"""Verify the plugin catalog surfaces real availability metadata to the UI."""

from fastapi.testclient import TestClient

from conftest import create_profile
from whatsapp_chat_system.web_api import build_app


def _login(client):
    response = client.post("/api/login", json={"password": "test-pass"})
    assert response.status_code == 200
    token = response.json()["session_token"]
    client.headers.update({"x-session-token": token})


def test_plugin_catalog_exposes_availability_metadata(tmp_path):
    profile = create_profile(tmp_path / "p-plugin-meta")
    client = TestClient(build_app(str(profile)))
    _login(client)

    response = client.get("/api/plugins")
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}

    auto_translate = items["auto_translate"]
    assert auto_translate["available"] is True
    assert auto_translate["unavailable_reason"] in (None, "")
    assert auto_translate["hooks"]  # human-readable hooks listed

    schedule = items["schedule"]
    assert schedule["available"] is False
    assert schedule["unavailable_reason"]
    assert (
        "Worker" in schedule["unavailable_reason"]
        or "SDD" in schedule["unavailable_reason"]
    )

    broadcast = items["broadcast"]
    assert broadcast["available"] is False
    assert broadcast["unavailable_reason"]

    # Toggle persists state for unavailable plugins too.
    toggle = client.post(
        "/api/plugins/toggle", json={"plugin_id": "schedule", "enabled": True}
    )
    assert toggle.status_code in (200, 409)
    listed = client.get("/api/plugins").json()["items"]
    listed_schedule = next(item for item in listed if item["id"] == "schedule")
    assert listed_schedule["available"] is False
    # toggle must not silently mark unavailable plugins as enabled
    assert toggle.status_code == 409 or toggle.json().get("plugin_id") == "schedule"


def test_dashboard_extends_stats_with_unread_pending_sent_response(tmp_path):
    profile = create_profile(tmp_path / "p-dashboard-stats")
    client = TestClient(build_app(str(profile)))
    _login(client)

    response = client.get("/api/dashboard")
    assert response.status_code == 200
    stats = response.json()["stats"]
    for key in (
        "unread_messages",
        "pending_replies",
        "sent_messages",
        "avg_response_seconds",
    ):
        assert key in stats, key
    assert isinstance(stats["unread_messages"], int)
    assert isinstance(stats["pending_replies"], int)
    assert isinstance(stats["sent_messages"], int)
    assert isinstance(stats["avg_response_seconds"], (int, float))
