"""Standalone plugin catalog and capability toggles."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from whatsapp_chat_system.runtime import StandaloneRuntime, save_runtime_settings


class PluginToggleRequest(BaseModel):
    plugin_id: str
    enabled: bool


PLUGIN_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "auto_translate", "name": "Auto translate", "description": "Translate non-Chinese inbound messages.",
        "category": "messaging", "builtin": True, "available": True,
        "unavailable_reason": None, "status_when_on": "实时翻译已接线", "hooks": ["/api/v1/messages/{message_id}/translate"],
    },
    {
        "id": "quick_reply", "name": "Quick reply", "description": "AI reply preview for the active conversation.",
        "category": "messaging", "builtin": True, "available": True,
        "unavailable_reason": None, "status_when_on": "AI 回复预览已接线", "hooks": ["/api/v1/conversations/{id}/reply"],
    },
    {
        "id": "persona_styles", "name": "Persona styles", "description": "Controlled built-in AI personas.",
        "category": "messaging", "builtin": True, "available": True,
        "unavailable_reason": None, "status_when_on": "受控 AI 人设已接线", "hooks": ["/api/v1/personas"],
    },
    {
        "id": "memory", "name": "Conversation memory", "description": "Persist conversation memory.",
        "category": "memory", "builtin": True, "available": True,
        "unavailable_reason": None, "status_when_on": "记忆读取已接线", "hooks": ["/api/v1/settings"],
    },
    {
        "id": "analytics", "name": "Analytics dashboard", "description": "Conversation and response statistics.",
        "category": "analytics", "builtin": True, "available": True,
        "unavailable_reason": None, "status_when_on": "真实统计已接线", "hooks": ["/api/v1/dashboard"],
    },
    {
        "id": "schedule", "name": "Scheduled send", "description": "Schedule messages for later delivery.",
        "category": "productivity", "builtin": True, "available": False,
        "unavailable_reason": "生产 Worker/真实 WhatsApp 投递尚未完成。", "status_when_on": "定时发送可用", "hooks": ["/api/v1/schedule"],
    },
    {
        "id": "broadcast", "name": "Mass broadcast", "description": "Send one message to multiple contacts.",
        "category": "productivity", "builtin": True, "available": False,
        "unavailable_reason": "群发限速、暂停/续跑和生产 Worker 尚未完成。", "status_when_on": "群发可用", "hooks": ["/api/v1/broadcast"],
    },
    {
        "id": "voice_tts", "name": "Voice playback (TTS)", "description": "Read messages aloud.",
        "category": "media", "builtin": True, "available": False,
        "unavailable_reason": "TTS provider 尚未接入。", "status_when_on": "TTS 可用", "hooks": [],
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
        values = state()
        return {"items": [{**item, "enabled": bool(values[item["id"]]) if item["available"] else False} for item in PLUGIN_CATALOG]}

    @router.post("/toggle")
    def toggle_plugin(payload: PluginToggleRequest) -> dict[str, Any]:
        item = next((entry for entry in PLUGIN_CATALOG if entry["id"] == payload.plugin_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="Unknown plugin")
        if payload.enabled and not item["available"]:
            raise HTTPException(status_code=409, detail={"code": "plugin_unavailable", "message": item["unavailable_reason"]})
        values = state()
        values[item["id"]] = bool(payload.enabled)
        save_runtime_settings(runtime)
        return {"success": True, "plugin_id": item["id"], "enabled": values[item["id"]]}

    @router.delete("/{plugin_id}")
    def disable_plugin(plugin_id: str) -> dict[str, Any]:
        item = next((entry for entry in PLUGIN_CATALOG if entry["id"] == plugin_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="Unknown plugin")
        values = state()
        values[plugin_id] = False
        save_runtime_settings(runtime)
        return {"success": True, "plugin_id": plugin_id, "enabled": False}

    return router
