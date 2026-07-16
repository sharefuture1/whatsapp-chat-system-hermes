"""Standalone settings, AI configuration, dashboard, and contact-scoped controls."""

from __future__ import annotations

import json
import ipaddress
import socket
from collections.abc import Callable, Generator
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from whatsapp_chat_system.authz import (
    require_admin,
    require_object_account_access,
    visible_account_ids_for,
)
from whatsapp_chat_system.ai.crypto import (
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
)
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
_SENSITIVE_SETTING_KEYS = frozenset(
    {
        "api_key",
        "api_key_ciphertext",
        "auth",
        "auth_policy",
        "hash",
        "login_attempts",
        "password",
        "salt",
        "secret",
        "sessions",
        "token",
        "users",
    }
)


class StandaloneSettingsUpdate(BaseModel):
    web_settings: dict[str, Any] = Field(default_factory=dict)
    channels: list[dict[str, Any]] | None = None


class AISettingsUpdate(BaseModel):
    base_url: str | None = Field(default=None, max_length=2048)
    default_model: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=512)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_retries: int | None = Field(default=None, ge=0, le=5)


class AITestRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=2048)
    default_model: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=512)


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
    return _redact_sensitive_settings(
        {
            key: deepcopy(value)
            for key, value in runtime.web_settings.items()
            if key in _SAFE_SETTING_SECTIONS
        }
    )


def _redact_sensitive_settings(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_sensitive_settings(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_SETTING_KEYS
        }
    if isinstance(value, list):
        return [_redact_sensitive_settings(item) for item in value]
    return value


def _unsafe_ai_base_url(message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "unsafe_ai_base_url", "message": message},
    )


def _validate_public_https_url(raw: str) -> str:
    """Fail closed for AI endpoints that send credentials to a remote host."""
    value = raw.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise _unsafe_ai_base_url("AI base URL is invalid") from exc
    if (
        parts.scheme.lower() != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise _unsafe_ai_base_url(
            "AI base URL must be an HTTPS URL without credentials, query, or fragment"
        )

    hostname = parts.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise _unsafe_ai_base_url("AI base URL must resolve to a public address")

    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            resolved = socket.getaddrinfo(
                hostname,
                port or 443,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise _unsafe_ai_base_url(
                "AI base URL hostname could not be resolved"
            ) from exc
        addresses = set()
        for item in resolved:
            address = str(item[4][0]).split("%", 1)[0]
            try:
                addresses.add(ipaddress.ip_address(address))
            except ValueError as exc:
                raise _unsafe_ai_base_url(
                    "AI base URL hostname resolved to an invalid address"
                ) from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise _unsafe_ai_base_url("AI base URL must resolve only to public addresses")

    normalized = _normalize_base_url(value)
    if normalized != value:
        raise _unsafe_ai_base_url("AI base URL is invalid")
    return normalized


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


def _ai_payload(
    runtime: StandaloneRuntime, row: AIRuntimeSetting | None
) -> dict[str, Any]:
    ciphertext = row.api_key_ciphertext if row else None
    env_key = runtime.ai_settings.api_key.strip()
    return {
        "provider": "wendingai",
        "base_url": row.base_url if row else runtime.ai_settings.base_url,
        "default_model": row.default_model
        if row
        else runtime.ai_settings.default_model,
        "timeout_seconds": row.timeout_seconds
        if row
        else runtime.ai_settings.timeout_seconds,
        "max_retries": row.max_retries if row else runtime.ai_settings.max_retries,
        "api_key_configured": bool(ciphertext and decrypt_api_key(ciphertext))
        or bool(env_key),
        "api_key_hint": row.api_key_hint if row else mask_api_key(env_key),
        "auto_translate": {
            "plugin_enabled": runtime.web_settings.get("plugins", {}).get(
                "auto_translate", True
            ),
            "setting_enabled": runtime.web_settings.get("message_ops", {}).get(
                "auto_translate", True
            ),
        },
    }


def _contact_payload(
    contact: Contact, override: ContactAIOverride | None
) -> dict[str, Any]:
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

    @router.get("/capabilities")
    def get_capabilities(request: Request) -> dict[str, Any]:
        visible_account_ids_for(runtime, request)
        message_ops = deepcopy(runtime.web_settings.get("message_ops") or {})
        reply = deepcopy(runtime.web_settings.get("reply") or {})
        plugins = deepcopy(runtime.web_settings.get("plugins") or {})
        auto_translate = {
            "plugin_enabled": plugins.get("auto_translate", True),
            "setting_enabled": message_ops.get("auto_translate", True),
        }
        return {
            "runtime_mode": "standalone",
            "message_ops": message_ops,
            "reply": {
                key: reply.get(key)
                for key in (
                    "default_reply_style",
                    "smart_max_length",
                    "translate_max_length",
                )
                if key in reply
            },
            "plugins": plugins,
            "auto_translate": auto_translate,
        }

    @router.get("/settings")
    def get_settings(
        request: Request, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        require_admin(runtime, request)
        ai_row = session.get(AIRuntimeSetting, "global")
        safe_web_settings = _safe_web_settings(runtime)
        return {
            "channels": deepcopy(runtime.forwarding_channels),
            "aliases": _load_aliases(runtime.paths.alias_file),
            "web_settings": safe_web_settings,
            "model": {
                "provider": "wendingai",
                "default": ai_row.default_model
                if ai_row
                else runtime.ai_settings.default_model,
                "base_url": ai_row.base_url if ai_row else runtime.ai_settings.base_url,
                "api_key_configured": _ai_payload(runtime, ai_row)[
                    "api_key_configured"
                ],
            },
            "plugins": deepcopy(safe_web_settings.get("plugins") or {}),
            "runtime_mode": "standalone",
        }

    @router.put("/settings")
    def update_settings(
        request: Request, payload: StandaloneSettingsUpdate
    ) -> dict[str, Any]:
        require_admin(runtime, request)
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
    def get_ai_settings(
        request: Request, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        require_admin(runtime, request)
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
        request: Request,
        payload: AISettingsUpdate,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        require_admin(runtime, request)
        row = session.get(AIRuntimeSetting, "global")
        if row is None:
            row = AIRuntimeSetting(id="global", provider="wendingai")
            session.add(row)
        if payload.base_url is not None:
            next_base_url = _validate_public_https_url(payload.base_url)
            current_base_url = (
                row.base_url if row.base_url else runtime.ai_settings.base_url
            )
            if (
                next_base_url != current_base_url
                and not (payload.api_key or "").strip()
            ):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "api_key_required_for_base_url_change",
                        "message": "Changing the AI base URL requires a new API key in the same request",
                    },
                )
            row.base_url = next_base_url
        if payload.default_model is not None:
            model = payload.default_model.strip()
            if not model:
                raise HTTPException(
                    status_code=422, detail="default_model must not be empty"
                )
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

    @router.post("/ai/test")
    def test_ai_connection(
        request: Request,
        payload: AITestRequest = Body(...),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        """
        Test AI connection with the given or currently configured credentials.
        Used by the Global AI settings page to verify connectivity before saving.
        """
        from whatsapp_chat_system.ai.provider import AIProviderError, WendingAIProvider

        require_admin(runtime, request)

        supplied_key = (payload.api_key or "").strip()
        supplied_base_url = (payload.base_url or "").strip()
        if supplied_base_url and not supplied_key:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "api_key_required_for_custom_base_url",
                    "message": "A custom AI base URL requires an API key in the same request",
                },
            )

        effective_key = supplied_key or None
        row = session.get(AIRuntimeSetting, "global")
        configured_base_url = (
            row.base_url if row and row.base_url else runtime.ai_settings.base_url
        )
        effective_base_url = supplied_base_url or configured_base_url
        effective_model = (payload.default_model or "").strip() or (
            row.default_model
            if row and row.default_model
            else runtime.ai_settings.default_model
        )

        if effective_key is None:
            if row and row.api_key_ciphertext:
                effective_key = decrypt_api_key(row.api_key_ciphertext)
            else:
                effective_key = runtime.ai_settings.api_key.strip() or None

        if not effective_key:
            return {"ok": False, "message": "No API key configured"}

        effective_base_url = _validate_public_https_url(effective_base_url)

        # Build a temporary provider to test
        from whatsapp_chat_system.settings import AISettings

        test_settings = AISettings(
            base_url=effective_base_url,
            api_key=effective_key,
            default_model=effective_model or "gpt-5.4",
            timeout_seconds=90,
            max_retries=2,
        )
        provider = WendingAIProvider(test_settings)

        try:
            result = provider.chat(
                model=effective_model,
                messages=[{"role": "user", "content": "Hi"}],
            )
            return {"ok": True, "message": f"Connected — model: {result.model}"}
        except AIProviderError as exc:
            return {"ok": False, "message": str(exc) or exc.code}
        except Exception:
            return {"ok": False, "message": "AI connection test failed"}

    @router.get("/dashboard")
    def dashboard(
        request: Request, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        visible_ids = visible_account_ids_for(runtime, request)
        account_filter = (
            WhatsAppAccount.id.in_(visible_ids) if visible_ids is not None else None
        )
        contact_filter = (
            Contact.account_id.in_(visible_ids) if visible_ids is not None else None
        )
        conversation_filter = (
            Conversation.account_id.in_(visible_ids)
            if visible_ids is not None
            else None
        )
        message_filter = (
            Message.account_id.in_(visible_ids) if visible_ids is not None else None
        )
        return {
            "runtime_mode": "standalone",
            "stats": {
                "accounts": session.scalar(
                    select(func.count(WhatsAppAccount.id)).where(account_filter)
                    if account_filter is not None
                    else select(func.count(WhatsAppAccount.id))
                )
                or 0,
                "online_accounts": session.scalar(
                    select(func.count(WhatsAppAccount.id)).where(
                        WhatsAppAccount.status == "online",
                        account_filter if account_filter is not None else True,
                    )
                )
                or 0,
                "contacts": session.scalar(
                    select(func.count(Contact.id)).where(contact_filter)
                    if contact_filter is not None
                    else select(func.count(Contact.id))
                )
                or 0,
                "conversations": session.scalar(
                    select(func.count(Conversation.id)).where(
                        Conversation.deleted_at.is_(None),
                        conversation_filter
                        if conversation_filter is not None
                        else True,
                    )
                )
                or 0,
                "messages": session.scalar(
                    select(func.count(Message.id)).where(message_filter)
                    if message_filter is not None
                    else select(func.count(Message.id))
                )
                or 0,
                "unread": session.scalar(
                    select(func.sum(Conversation.unread_count)).where(
                        conversation_filter
                    )
                    if conversation_filter is not None
                    else select(func.sum(Conversation.unread_count))
                )
                or 0,
            },
            "recent_conversations": [],
            "plugins_enabled": sum(
                1
                for enabled in (runtime.web_settings.get("plugins") or {}).values()
                if enabled
            ),
        }

    @router.get("/contacts/{contact_id}/settings")
    def get_contact_settings(
        request: Request,
        contact_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        contact = session.get(Contact, contact_id)
        if contact is None:
            raise HTTPException(status_code=404, detail="Contact not found")
        require_object_account_access(
            runtime,
            request,
            contact.account_id,
            not_found_detail="Contact not found",
        )
        override = session.get(ContactAIOverride, (contact.account_id, contact.id))
        return _contact_payload(contact, override)

    @router.put("/contacts/{contact_id}/settings")
    def update_contact_settings(
        request: Request,
        contact_id: str,
        payload: ContactSettingsUpdate,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        contact = session.get(Contact, contact_id)
        if contact is None:
            raise HTTPException(status_code=404, detail="Contact not found")
        require_object_account_access(
            runtime,
            request,
            contact.account_id,
            write=True,
            not_found_detail="Contact not found",
        )
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
                    values["custom_system_prompt"] or ""
                ).strip() or None
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
