"""Standalone settings, AI configuration, dashboard, and contact-scoped controls."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from whatsapp_chat_system.ai.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from whatsapp_chat_system.db.models import (
    AIRuntimeSetting,
    Contact,
    ContactAIOverride,
    Conversation,
    Message,
    WhatsAppAccount,
)
from whatsapp_chat_system.runtime import StandaloneRuntime, save_runtime_settings
from whatsapp_chat_system.settings import _normalize_base_url


_SAFE_SETTING_SECTIONS = frozenset({"ui", "message_ops", "reply", "plugins"})


class StandaloneSettingsUpdate(BaseModel):
    web_settings: dict[str, Any] = Field(default_factory=dict)
    channels: list[dict[str, Any]] | None = None


class AISettingsUpdate(BaseModel):
    base_url: str | None = Field(default=None, max_length=2048)
    default_model: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=512)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_retries: int | None = Field(default=None, ge=0, le=5)


class ContactSettingsUpdate(BaseModel):
    remark: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=10000)
    tags: list[str] | None = None
    language: str | None = Field(default=None, max_length=32)
    ai_model: str | None = Field(default=None, max_length=255)
    custom_system_prompt: str | None = Field(default=None, max_length=20000)
    reply_style: str | None = Field(default=None, max_length=10000)
    auto_reply_enabled: bool | None = None


def _deep_merge(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(current)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _safe_web_settings(runtime: StandaloneRuntime) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in runtime.web_settings.items()
        if key not in {"auth", "sessions", "login_attempts", "auth_policy"}
    }


def _load_aliases(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_channels(runtime: StandaloneRuntime, channels: list[dict[str, Any]]) -> None:
    encoded = json.dumps(channels, ensure_ascii=False, indent=2)
    temporary = runtime.paths.admin_channels_file.with_suffix(".json.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(runtime.paths.admin_channels_file)
    runtime.forwarding_channels = channels


def _ai_payload(runtime: StandaloneRuntime, row: AIRuntimeSetting | None) -> dict[str, Any]:
    ciphertext = row.api_key_ciphertext if row else None
    env_key = runtime.ai_settings.api_key.strip()
    return {
        "provider": "wendingai",
        "base_url": row.base_url if row else runtime.ai_settings.base_url,
        "default_model": row.default_model if row else runtime.ai_settings.default_model,
        "timeout_seconds": row.timeout_seconds if row else runtime.ai_settings.timeout_seconds,
        "max_retries": row.max_retries if row else runtime.ai_settings.max_retries,
        "api_key_configured": bool(ciphertext and decrypt_api_key(ciphertext)) or bool(env_key),
        "api_key_hint": row.api_key_hint if row else mask_api_key(env_key),
        "auto_translate": {
            "plugin_enabled": runtime.web_settings.get("plugins", {}).get("auto_translate", True),
            "setting_enabled": runtime.web_settings.get("message_ops", {}).get("auto_translate", True),
        },
    }


def _contact_payload(contact: Contact, override: ContactAIOverride | None) -> dict[str, Any]:
    return {
        "contact_id": contact.id,
        "account_id": contact.account_id,
        "remote_jid": contact.remote_jid,
        "remark": contact.remark,
        "notes": contact.notes,
        "tags": contact.tags or [],
        "language": contact.language,
        "ai_model": override.model if override else None,
        "custom_system_prompt": override.system_prompt if override else None,
        "reply_style": override.reply_style if override else None,
        "auto_reply_enabled": override.auto_reply_enabled if override else None,
    }


def create_settings_router(
    runtime: StandaloneRuntime,
    session_factory: Callable[[], Session],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["settings"])

    def get_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    @router.get("/settings")
    def get_settings(session: Session = Depends(get_session)) -> dict[str, Any]:
        ai_row = session.get(AIRuntimeSetting, "global")
        return {
            "channels": deepcopy(runtime.forwarding_channels),
            "aliases": _load_aliases(runtime.paths.alias_file),
            "web_settings": _safe_web_settings(runtime),
            "model": {
                "provider": "wendingai",
                "default": ai_row.default_model if ai_row else runtime.ai_settings.default_model,
                "base_url": ai_row.base_url if ai_row else runtime.ai_settings.base_url,
                "api_key_configured": _ai_payload(runtime, ai_row)["api_key_configured"],
            },
            "plugins": deepcopy(runtime.web_settings.get("plugins") or {}),
            "runtime_mode": "standalone",
        }

    @router.put("/settings")
    def update_settings(payload: StandaloneSettingsUpdate) -> dict[str, Any]:
        disallowed = set(payload.web_settings) - _SAFE_SETTING_SECTIONS
        if disallowed:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unsupported_settings_section",
                    "message": f"Unsupported settings sections: {', '.join(sorted(disallowed))}",
                },
            )
        runtime.web_settings = _deep_merge(runtime.web_settings, payload.web_settings)
        save_runtime_settings(runtime)
        if payload.channels is not None:
            _write_channels(runtime, payload.channels)
        return {
            "success": True,
            "channels": deepcopy(runtime.forwarding_channels),
            "web_settings": _safe_web_settings(runtime),
        }

    @router.get("/ai/settings")
    def get_ai_settings(session: Session = Depends(get_session)) -> dict[str, Any]:
        payload = _ai_payload(runtime, session.get(AIRuntimeSetting, "global"))
        auto_translate = payload["auto_translate"]
        configured = bool(payload["api_key_configured"])
        auto_translate["ai_configured"] = configured
        auto_translate["ready"] = bool(
            auto_translate["plugin_enabled"]
            and auto_translate["setting_enabled"]
            and configured
        )
        auto_translate["blocked_reason"] = (
            None
            if auto_translate["ready"]
            else "plugin_disabled"
            if not auto_translate["plugin_enabled"]
            else "setting_disabled"
            if not auto_translate["setting_enabled"]
            else "ai_not_configured"
        )
        return payload

    @router.put("/ai/settings")
    def update_ai_settings(
        payload: AISettingsUpdate,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        row = session.get(AIRuntimeSetting, "global")
        if row is None:
            row = AIRuntimeSetting(id="global", provider="wendingai")
            session.add(row)
        if payload.base_url is not None:
            normalized = _normalize_base_url(payload.base_url)
            if normalized != payload.base_url.strip().rstrip("/"):
                raise HTTPException(status_code=422, detail="Invalid AI base URL")
            row.base_url = normalized
        if payload.default_model is not None:
            model = payload.default_model.strip()
            if not model:
                raise HTTPException(status_code=422, detail="default_model must not be empty")
            row.default_model = model
        if payload.api_key is not None:
            key = payload.api_key.strip()
            row.api_key_ciphertext = encrypt_api_key(key) if key else None
            row.api_key_hint = mask_api_key(key)
        if payload.timeout_seconds is not None:
            row.timeout_seconds = payload.timeout_seconds
        if payload.max_retries is not None:
            row.max_retries = payload.max_retries
        session.commit()
        return {"success": True, **_ai_payload(runtime, row)}

    @router.get("/dashboard")
    def dashboard(session: Session = Depends(get_session)) -> dict[str, Any]:
        return {
            "runtime_mode": "standalone",
            "stats": {
                "accounts": session.scalar(select(func.count(WhatsAppAccount.id))) or 0,
                "online_accounts": session.scalar(
                    select(func.count(WhatsAppAccount.id)).where(
                        WhatsAppAccount.status == "online"
                    )
                )
                or 0,
                "contacts": session.scalar(select(func.count(Contact.id))) or 0,
                "conversations": session.scalar(
                    select(func.count(Conversation.id)).where(
                        Conversation.deleted_at.is_(None)
                    )
                )
                or 0,
                "messages": session.scalar(select(func.count(Message.id))) or 0,
                "unread": session.scalar(select(func.sum(Conversation.unread_count))) or 0,
            },
            "recent_conversations": [],
            "plugins_enabled": sum(
                1 for enabled in (runtime.web_settings.get("plugins") or {}).values() if enabled
            ),
        }

    @router.get("/contacts/{contact_id}/settings")
    def get_contact_settings(
        contact_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        contact = session.get(Contact, contact_id)
        if contact is None:
            raise HTTPException(status_code=404, detail="Contact not found")
        override = session.get(ContactAIOverride, (contact.account_id, contact.id))
        return _contact_payload(contact, override)

    @router.put("/contacts/{contact_id}/settings")
    def update_contact_settings(
        contact_id: str,
        payload: ContactSettingsUpdate,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        contact = session.get(Contact, contact_id)
        if contact is None:
            raise HTTPException(status_code=404, detail="Contact not found")
        values = payload.model_dump(exclude_unset=True)
        if "remark" in values:
            contact.remark = (values["remark"] or "").strip() or None
        if "notes" in values:
            contact.notes = (values["notes"] or "").strip() or None
        if "tags" in values:
            contact.tags = list(dict.fromkeys(values["tags"] or []))[:100]
        if "language" in values:
            contact.language = (values["language"] or "").strip() or None
        contact.profile_revision += 1

        override_fields = {
            "ai_model",
            "custom_system_prompt",
            "reply_style",
            "auto_reply_enabled",
        }
        override = session.get(ContactAIOverride, (contact.account_id, contact.id))
        if override is None and override_fields.intersection(values):
            override = ContactAIOverride(
                account_id=contact.account_id,
                contact_id=contact.id,
            )
            session.add(override)
        if override is not None:
            if "ai_model" in values:
                override.model = (values["ai_model"] or "").strip() or None
            if "custom_system_prompt" in values:
                override.system_prompt = (
                    (values["custom_system_prompt"] or "").strip() or None
                )
            if "reply_style" in values:
                override.reply_style = (values["reply_style"] or "").strip() or None
            if "auto_reply_enabled" in values:
                override.auto_reply_enabled = values["auto_reply_enabled"]
        session.commit()
        return {
            "success": True,
            **_contact_payload(contact, override),
        }

    return router
