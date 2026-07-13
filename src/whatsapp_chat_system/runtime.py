"""Standalone API runtime configuration with no Hermes profile dependency."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .settings import AISettings


@dataclass(frozen=True, slots=True)
class StandaloneRuntimePaths:
    root: Path
    web_settings_file: Path
    admin_channels_file: Path
    alias_file: Path


@dataclass(slots=True)
class StandaloneRuntime:
    """Configuration persisted below the independently configured runtime root."""

    paths: StandaloneRuntimePaths
    ai_settings: AISettings
    internal_event_token: str
    forwarding_channels: list[dict[str, Any]] = field(default_factory=list)
    web_settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(
        cls,
        runtime_dir: str | Path | None = None,
        *,
        internal_event_token: str | None = None,
    ) -> "StandaloneRuntime":
        root = _resolve_runtime_dir(runtime_dir)
        database_url = (os.getenv("DATABASE_URL") or "").strip()
        token = (
            internal_event_token
            if internal_event_token is not None
            else os.getenv("WHATSAPP_BRIDGE_INTERNAL_TOKEN")
        )
        token = (token or "").strip()
        if (
            not database_url
            or database_url == "sqlite:///./data/whatsapp-chat-system.db"
        ):
            raise RuntimeError("standalone runtime configuration requires DATABASE_URL")
        if not token:
            raise RuntimeError(
                "standalone runtime configuration requires WHATSAPP_BRIDGE_INTERNAL_TOKEN"
            )

        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        paths = StandaloneRuntimePaths(
            root=root,
            web_settings_file=root / "web-settings.json",
            admin_channels_file=root / "admin-channels.json",
            alias_file=root / "user-aliases.json",
        )
        if not paths.web_settings_file.exists():
            # Bootstrap is the only path that consumes the one-time password.
            web_settings = _default_web_settings()
        else:
            # Do not call _default_web_settings here: a restart must not require
            # the bootstrap secret after the password record was persisted.
            web_settings = _load_json(paths.web_settings_file, None)
            if not isinstance(web_settings, dict) or not _is_valid_password_record(
                web_settings.get("auth")
            ):
                raise RuntimeError("invalid standalone runtime authentication settings")
            web_settings = _merge(_existing_web_settings_defaults(), web_settings)
        _save_json(paths.web_settings_file, web_settings)
        channels = _load_json(paths.admin_channels_file, [])
        if not isinstance(channels, list):
            channels = []
            _save_json(paths.admin_channels_file, channels)
        return cls(
            paths=paths,
            ai_settings=AISettings.from_env(),
            internal_event_token=token,
            forwarding_channels=channels,
            web_settings=web_settings,
        )


def _resolve_runtime_dir(runtime_dir: str | Path | None) -> Path:
    raw = (
        str(runtime_dir)
        if runtime_dir is not None
        else os.getenv("CHAT_SYSTEM_RUNTIME_DIR", "")
    )
    if not raw:
        raise RuntimeError(
            "standalone runtime configuration requires CHAT_SYSTEM_RUNTIME_DIR"
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RuntimeError("CHAT_SYSTEM_RUNTIME_DIR must be an absolute path")
    return path


def _default_web_settings() -> dict[str, Any]:
    password = os.getenv("CHAT_SYSTEM_BOOTSTRAP_PASSWORD", "")
    if len(password) < 12:
        raise RuntimeError(
            "standalone runtime configuration requires CHAT_SYSTEM_BOOTSTRAP_PASSWORD with at least 12 characters"
        )

    return {
        "auth": _build_password_record(password),
        **_existing_web_settings_defaults(),
    }


def _existing_web_settings_defaults() -> dict[str, Any]:
    """Safe non-secret defaults used when loading an existing runtime."""
    return {
        "auth_required": True,
        "auth_ttl_seconds": 86400,
        "message_ops": {"auto_translate": True},
        "plugins": {},
        "sessions": {},
    }


def _merge(defaults: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid standalone runtime settings JSON: {path}") from exc


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_runtime_settings(runtime: StandaloneRuntime) -> None:
    """Persist settings with the same atomic, restrictive policy as bootstrap."""
    _save_json(runtime.paths.web_settings_file, runtime.web_settings)


def _build_password_record(password: str, iterations: int = 600000) -> dict[str, Any]:
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), iterations
    )
    return {
        "scheme": "pbkdf2_sha256",
        "salt": salt,
        "iterations": iterations,
        "hash": derived.hex(),
    }


def _is_valid_password_record(record: Any) -> bool:
    """Reject malformed persisted authentication data rather than weakening startup."""
    if not isinstance(record, dict) or record.get("scheme") != "pbkdf2_sha256":
        return False
    salt, digest, iterations = (
        record.get("salt"),
        record.get("hash"),
        record.get("iterations"),
    )
    if not isinstance(salt, str) or not salt or not isinstance(digest, str):
        return False
    if (
        not isinstance(iterations, int)
        or isinstance(iterations, bool)
        or iterations <= 0
    ):
        return False
    try:
        return len(bytes.fromhex(digest)) == 32
    except ValueError:
        return False
