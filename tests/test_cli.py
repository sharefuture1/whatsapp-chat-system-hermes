"""Task 1 deployment-contract regressions (FR-CORE-001/002, MIG-001/002, QA-001)."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "deploy" / "systemd"
API_UNIT = SYSTEMD / "whatsapp-chat-system.service"
BRIDGE_UNIT = SYSTEMD / "whatsapp-bridge-v2.service"


def unit_values(text: str, key: str) -> list[str]:
    return [
        line.split("=", 1)[1]
        for line in text.splitlines()
        if line.startswith(f"{key}=")
    ]


def test_serve_deployment_contract_has_no_profile_and_uses_independent_environment():
    """The production `serve` invocation must not select a Hermes profile."""
    text = API_UNIT.read_text(encoding="utf-8")

    assert "WorkingDirectory=/opt/whatsapp-chat-system" in text
    assert "EnvironmentFile=-/etc/whatsapp-chat-system/api.env" in text
    assert (
        "/opt/whatsapp-chat-system/.venv/bin/python -m whatsapp_chat_system.cli serve"
        in text
    )
    assert "--profile" not in text
    assert ".hermes" not in text.lower()
    assert "CHAT_SYSTEM_RUNTIME_DIR" in text
    assert "DATABASE_URL" in text
    assert "WHATSAPP_BRIDGE_INTERNAL_TOKEN" in text


def test_bridge_v2_unit_is_loopback_and_uses_only_independent_runtime_root():
    text = BRIDGE_UNIT.read_text(encoding="utf-8")

    assert "WorkingDirectory=/opt/whatsapp-chat-system/bridge" in text
    assert "EnvironmentFile=-/etc/whatsapp-chat-system/bridge.env" in text
    assert "Environment=BRIDGE_HOST=127.0.0.1" in text
    assert "Environment=BRIDGE_PORT=3100" in text
    assert (
        "Environment=BRIDGE_RUNTIME_ROOT=/var/lib/whatsapp-chat-system/bridge" in text
    )
    assert "/usr/bin/node /opt/whatsapp-chat-system/bridge/src/index.js" in text
    assert ".hermes" not in text.lower()
    assert "--profile" not in text


def test_service_assets_do_not_embed_credentials_or_legacy_runtime_paths():
    for unit_path in (API_UNIT, BRIDGE_UNIT):
        text = unit_path.read_text(encoding="utf-8")
        assert "/root/.hermes" not in text
        assert "WHATSAPP_BRIDGE_INTERNAL_TOKEN=" not in text
        assert "DATABASE_URL=" not in text
        assert all(
            "=" not in value or value.startswith("-")
            for value in unit_values(text, "EnvironmentFile")
        )
