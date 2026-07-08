from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import hashlib
import secrets
import os

import yaml

from .constants import DEFAULT_ADMIN_IDS, DEFAULT_ADMIN_TARGET, DEFAULT_PROFILE


@dataclass(slots=True)
class AppPaths:
    profile: Path
    db: Path
    sessions_json: Path
    channel_directory: Path
    alias_file: Path
    config_file: Path
    log_dir: Path
    memory_dir: Path
    router_state: Path
    forward_state: Path
    admin_channels_file: Path
    web_settings_file: Path


@dataclass(slots=True)
class AppConfig:
    paths: AppPaths
    admin_ids: set[str]
    admin_target: str
    model: dict[str, str]
    forwarding_channels: list[dict[str, Any]] = field(default_factory=list)
    web_settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile: str | Path | None = None) -> "AppConfig":
        profile_path = Path(profile) if profile else DEFAULT_PROFILE
        paths = AppPaths(
            profile=profile_path,
            db=profile_path / "state.db",
            sessions_json=profile_path / "sessions" / "sessions.json",
            channel_directory=profile_path / "channel_directory.json",
            alias_file=profile_path / "user-aliases.json",
            config_file=profile_path / "config.yaml",
            log_dir=profile_path / "logs",
            memory_dir=profile_path / "user-memory-md",
            router_state=profile_path / ".admin-command-router-state.json",
            forward_state=profile_path / ".admin-forward-state.json",
            admin_channels_file=profile_path / "admin-channels.json",
            web_settings_file=profile_path / "web-settings.json",
        )
        paths.log_dir.mkdir(parents=True, exist_ok=True)
        paths.memory_dir.mkdir(parents=True, exist_ok=True)
        cfg = load_yaml(paths.config_file)
        whatsapp_cfg = cfg.get("whatsapp") or {}
        admin_ids = set(DEFAULT_ADMIN_IDS)
        admin_ids.update(str(x) for x in whatsapp_cfg.get("allow_admin_from") or [])
        admin_ids.update(str(x) for x in whatsapp_cfg.get("group_allow_admin_from") or [])
        model_cfg = cfg.get("model") or {}
        channels = load_json(paths.admin_channels_file, None)
        if not isinstance(channels, list):
            channels = [
                {
                    "id": "default-whatsapp-admin",
                    "name": "WhatsApp Admin",
                    "platform": "whatsapp",
                    "target": DEFAULT_ADMIN_TARGET,
                    "enabled": True,
                    "kinds": ["reply_ack", "conversation_forward", "system_alert"],
                }
            ]
            save_json(paths.admin_channels_file, channels)
        web_settings = load_json(paths.web_settings_file, None)
        if not isinstance(web_settings, dict):
            web_settings = default_web_settings()
            save_json(paths.web_settings_file, web_settings)
        else:
            merged = merge_web_settings(default_web_settings(), web_settings)
            if merged != web_settings:
                web_settings = merged
                save_json(paths.web_settings_file, web_settings)
        return cls(
            paths=paths,
            admin_ids=admin_ids,
            admin_target=DEFAULT_ADMIN_TARGET,
            model={
                "model": str(model_cfg.get("default") or ""),
                "base_url": str(model_cfg.get("base_url") or ""),
                "api_key": str(model_cfg.get("api_key") or ""),
            },
            forwarding_channels=channels,
            web_settings=web_settings,
        )


def default_web_settings() -> dict[str, Any]:
    default_password = os.getenv('CHAT_SYSTEM_BOOTSTRAP_PASSWORD', 'test?9')
    return {
        "auth": build_password_record(default_password),
        "auth_required": True,
        "auth_ttl_seconds": 86400,
        "reply": {
            "default_mode": "direct",
            "smart_max_length": 40,
            "translate_max_length": 60,
            "allow_fallback": True,
            "preview_debounce_ms": 320,
            "prefer_detected_language": True,
        },
        "ui": {
            "auto_refresh_seconds": 10,
            "show_preview_before_send": True,
        },
        "message_ops": {
            "allow_local_hide_delete": True,
            "allow_bulk_local_hide": True,
            "remote_delete_supported": False,
            "auto_translate": True,
        },
        "hidden_message_ids": [],
        "sessions": {},
    }


def merge_web_settings(defaults: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_web_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_password_record(password: str, iterations: int = 600000) -> dict[str, Any]:
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
    return {
        "scheme": "pbkdf2_sha256",
        "salt": salt,
        "iterations": iterations,
        "hash": derived.hex(),
    }


def verify_password(stored: dict[str, Any], candidate: str) -> bool:
    scheme = str(stored.get('scheme') or '')
    if scheme == 'pbkdf2_sha256':
        salt = str(stored.get('salt') or '')
        expected = str(stored.get('hash') or '')
        iterations = int(stored.get('iterations') or 0)
        if not salt or not expected or not iterations:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', candidate.encode(), salt.encode(), iterations).hex()
        return secrets.compare_digest(actual, expected)
    salt = str(stored.get("salt") or "")
    expected = str(stored.get("sha256") or "")
    if not salt or not expected:
        return False
    actual = hashlib.sha256(f"{salt}:{candidate}".encode()).hexdigest()
    return secrets.compare_digest(actual, expected)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text())
    return data if isinstance(data, dict) else {}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
