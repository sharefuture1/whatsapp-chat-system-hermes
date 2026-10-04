"""Standalone plugin catalog and capability toggles."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from whatsapp_chat_system.authz import require_admin
from whatsapp_chat_system.runtime import StandaloneRuntime, save_runtime_settings


class PluginToggleRequest(BaseModel):
    plugin_id: str
    enabled: bool


PLUGIN_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "auto_translate",
        "name": "Auto translate",
        "description": "Translate non-Chinese inbound messages.",
        "category": "messaging",
        "builtin": True,
        "available": True,
        "unavailable_reason": None,
        "status_when_on": "入站与手动翻译运行时已接线",
        "hooks": [
            "message.ingested",
            "/api/v1/conversations/{id}/translations",
        ],
    },
    {
        "id": "quick_reply",
        "name": "Quick reply",
        "description": "AI reply preview for the active conversation.",
        "category": "messaging",
        "builtin": True,
        "available": True,
        "unavailable_reason": None,
        "status_when_on": "AI 回复预览运行时已接线",
        "hooks": ["/api/v1/conversations/{id}/reply"],
    },
    {
        "id": "persona_styles",
        "name": "Persona styles",
        "description": "Controlled built-in AI personas.",
        "category": "messaging",
        "builtin": True,
        "available": True,
        "unavailable_reason": None,
        "status_when_on": "受控 AI 人设运行时已接线",
        "hooks": ["/api/v1/personas", "/api/v1/contacts/{id}/persona"],
    },
    {
        "id": "memory",
        "name": "Conversation memory",
        "description": "Persist conversation memory.",
        "category": "memory",
        "builtin": True,
        "available": False,
        "unavailable_reason": "独立记忆 Worker 与检索链路尚未完成，不能作为可开关插件发布。",
        "status_when_on": "记忆可用",
        "hooks": [],
    },
    {
        "id": "analytics",
        "name": "Analytics dashboard",
        "description": "Conversation and response statistics.",
        "category": "analytics",
        "builtin": True,
        "available": False,
        "unavailable_reason": "Dashboard 目前属于核心运行状态，尚未拆成可独立关闭的插件。",
        "status_when_on": "统计插件可用",
        "hooks": [],
    },
    {
        "id": "schedule",
        "name": "Scheduled send",
        "description": "Schedule messages for later delivery.",
        "category": "productivity",
        "builtin": True,
        "available": False,
        "unavailable_reason": "生产 Worker/真实 WhatsApp 投递尚未完成。",
        "status_when_on": "定时发送可用",
        "hooks": ["/api/v1/schedule"],
    },
    {
        "id": "broadcast",
        "name": "Mass broadcast",
        "description": "Send one message to multiple contacts.",
        "category": "productivity",
        "builtin": True,
        "available": False,
        "unavailable_reason": "群发限速、暂停/续跑和生产 Worker 尚未完成。",
        "status_when_on": "群发可用",
        "hooks": ["/api/v1/broadcast"],
    },
    {
        "id": "voice_tts",
        "name": "Voice playback (TTS)",
        "description": "Read messages aloud.",
        "category": "media",
        "builtin": True,
        "available": False,
        "unavailable_reason": "TTS provider 尚未接入。",
        "status_when_on": "TTS 可用",
        "hooks": [],
    },
)


def plugin_definition(plugin_id: str) -> dict[str, Any] | None:
    return next((item for item in PLUGIN_CATALOG if item["id"] == plugin_id), None)


def plugin_enabled(runtime: StandaloneRuntime, plugin_id: str) -> bool:
    item = plugin_definition(plugin_id)
    if item is None or not item["available"]:
        return False
    values = runtime.web_settings.get("plugins") or {}
    return bool(values.get(plugin_id, True))


def require_plugin_enabled(runtime: StandaloneRuntime, plugin_id: str) -> None:
    item = plugin_definition(plugin_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Unknown plugin")
    if not item["available"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "plugin_unavailable",
                "message": item["unavailable_reason"],
            },
        )
    if not plugin_enabled(runtime, plugin_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "plugin_disabled",
                "message": f"Plugin is disabled: {plugin_id}",
            },
        )


def create_plugins_router(runtime: StandaloneRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/v1/plugins", tags=["plugins"])

    def state() -> dict[str, bool]:
        values = runtime.web_settings.setdefault("plugins", {})
        for item in PLUGIN_CATALOG:
            values.setdefault(item["id"], True if item["available"] else False)
        return values

    @router.get("")
    def list_plugins() -> dict[str, Any]:
        state()
        return {
            "items": [
                {
                    **item,
                    "enabled": plugin_enabled(runtime, item["id"]),
                }
                for item in PLUGIN_CATALOG
            ]
        }

    @router.post("/toggle")
    def toggle_plugin(
        request: Request, payload: PluginToggleRequest
    ) -> dict[str, Any]:
        require_admin(runtime, request)
        item = plugin_definition(payload.plugin_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Unknown plugin")
        if payload.enabled and not item["available"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "plugin_unavailable",
                    "message": item["unavailable_reason"],
                },
            )
        values = state()
        values[item["id"]] = bool(payload.enabled)
        save_runtime_settings(runtime)
        return {
            "success": True,
            "plugin_id": item["id"],
            "enabled": plugin_enabled(runtime, item["id"]),
        }

    @router.delete("/{plugin_id}")
    def disable_plugin(request: Request, plugin_id: str) -> dict[str, Any]:
        require_admin(runtime, request)
        item = plugin_definition(plugin_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Unknown plugin")
        values = state()
        values[plugin_id] = False
        save_runtime_settings(runtime)
        return {"success": True, "plugin_id": plugin_id, "enabled": False}

    return router


__all__ = [
    "PLUGIN_CATALOG",
    "create_plugins_router",
    "plugin_definition",
    "plugin_enabled",
    "require_plugin_enabled",
]
