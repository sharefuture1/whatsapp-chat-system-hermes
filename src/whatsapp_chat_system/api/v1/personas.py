"""FR-PLG-007/008 + FR-AI-012：受控内置人设 V1 API。

只读、写受控人设目录元数据；写入仅作用于 ``web_settings.plugins.persona_styles``
和 ``web_settings.contact_profiles[contact_id].persona_id``。所有错误响应标准化为
``{"detail": {"code": ..., "message": ...}}``。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from whatsapp_chat_system.personas import list_personas
from whatsapp_chat_system.runtime import StandaloneRuntime


def _known_persona_ids() -> set[str]:
    """包含 default 的全部受控人设 ID。"""
    return {"default", "tong-jincheng", "professional-service", "mature-uncle"}


def _is_valid_persona(persona_id: str) -> bool:
    return persona_id in _known_persona_ids()


class PersonaEnableRequest(BaseModel):
    enabled: bool


class PersonaAssignRequest(BaseModel):
    persona_id: str | None = Field(default=None, max_length=64)


def _web_settings(runtime: StandaloneRuntime) -> dict[str, Any]:
    settings = dict(runtime.web_settings or {})
    settings.setdefault("plugins", {})
    settings.setdefault("contact_profiles", {})
    return settings


def _persist_web_settings(runtime: StandaloneRuntime) -> None:
    from whatsapp_chat_system.runtime import (
        save_runtime_settings,
    )  # local import avoids cycle

    save_runtime_settings(runtime)


def _is_authenticated(runtime: StandaloneRuntime, request: Request) -> bool:
    token = request.headers.get("x-session-token", "")
    sessions = runtime.web_settings.get("sessions") or {}
    session = sessions.get(token)
    if not session:
        return False
    return float(session.get("expires_at", 0)) > __import__("time").time()


def _unauthorized(request: Request) -> JSONResponse:
    request_id = (
        request.headers.get("X-Request-ID")
        or f"req_{__import__('secrets').token_hex(16)}"
    )
    return JSONResponse(
        {"detail": {"code": "unauthorized", "message": "Authentication required"}},
        status_code=401,
        headers={"X-Request-ID": request_id},
    )


def create_personas_router(
    runtime: Any,
    session_factory: Callable[[], Session] | None = None,
) -> APIRouter:
    """``runtime`` 只读 ``web_settings`` 字段；AppConfig 与 StandaloneRuntime 兼容。"""
    router = APIRouter(prefix="/api/v1", tags=["personas"])

    def _get_session() -> Generator[Session, None, None]:
        if session_factory is None:
            return
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    @router.get("/personas")
    def list_endpoint(request: Request):
        if not _is_authenticated(runtime, request):
            return _unauthorized(request)
        settings = _web_settings(runtime)
        enabled_flag = bool(settings.get("plugins", {}).get("persona_styles", True))
        items = [item for item in list_personas() if _is_valid_persona(item["id"])]
        contact_profiles = settings.get("contact_profiles") or {}
        contact_assignments = {
            str(contact_id): str(profile.get("persona_id") or "default")
            for contact_id, profile in contact_profiles.items()
            if isinstance(profile, dict)
            and profile.get("persona_id")
            and profile.get("persona_id") != "default"
        }
        return {
            "items": [{**item, "available": True} for item in items],
            "contact_assignments": contact_assignments,
            "plugin_enabled": enabled_flag,
        }

    @router.put("/personas/{persona_id}/enable")
    def enable_endpoint(
        persona_id: str, payload: PersonaEnableRequest, request: Request
    ):
        if not _is_authenticated(runtime, request):
            return _unauthorized(request)
        if not _is_valid_persona(persona_id):
            return JSONResponse(
                {
                    "detail": {
                        "code": "persona_not_found",
                        "message": f"Unknown persona: {persona_id}",
                    }
                },
                status_code=404,
            )
        if persona_id == "default":
            return JSONResponse(
                {
                    "detail": {
                        "code": "persona_default_immutable",
                        "message": "Default persona cannot be toggled",
                    }
                },
                status_code=400,
            )
        settings = _web_settings(runtime)
        settings.setdefault("plugins", {})
        settings["plugins"]["persona_styles"] = bool(payload.enabled)
        runtime.web_settings = settings
        _persist_web_settings(runtime)
        return {"id": persona_id, "enabled": bool(payload.enabled)}

    @router.put("/contacts/{contact_id}/persona")
    def assign_endpoint(
        contact_id: str, payload: PersonaAssignRequest, request: Request
    ):
        if not _is_authenticated(runtime, request):
            return _unauthorized(request)
        persona_id = payload.persona_id or "default"
        if not _is_valid_persona(persona_id):
            return JSONResponse(
                {
                    "detail": {
                        "code": "persona_not_found",
                        "message": f"Unknown persona: {persona_id}",
                    }
                },
                status_code=404,
            )
        settings = _web_settings(runtime)
        contact_profiles = dict(settings.get("contact_profiles") or {})
        profile = dict(contact_profiles.get(contact_id) or {})
        if persona_id == "default":
            profile.pop("persona_id", None)
        else:
            profile["persona_id"] = persona_id
        if profile:
            contact_profiles[contact_id] = profile
        else:
            contact_profiles.pop(contact_id, None)
        settings["contact_profiles"] = contact_profiles
        runtime.web_settings = settings
        _persist_web_settings(runtime)
        return {"contact_id": contact_id, "persona_id": persona_id}

    return router


__all__ = ["create_personas_router"]
