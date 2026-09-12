from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AutoTranslationPolicy:
    enabled: bool
    plugin_enabled: bool
    setting_enabled: bool
    ai_configured: bool
    target_lang: str
    window_size: int
    blocked_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin_enabled": self.plugin_enabled,
            "setting_enabled": self.setting_enabled,
            "ai_configured": self.ai_configured,
            "ready": self.enabled,
            "blocked_reason": self.blocked_reason,
            "target_lang": self.target_lang,
            "window_size": self.window_size,
        }


def _bool_setting(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _window_size(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 10
    return max(1, min(20, parsed))


def resolve_auto_translation_policy(
    web_settings: dict[str, Any] | None,
    *,
    ai_configured: bool,
) -> AutoTranslationPolicy:
    """Resolve the one authoritative Standalone automatic-translation gate.

    Manual/backfill translation APIs intentionally do not use this gate.  It only
    decides whether an inbound WhatsApp event may create automatic translation work.
    """

    settings = web_settings or {}
    plugins = settings.get("plugins") if isinstance(settings.get("plugins"), dict) else {}
    message_ops = (
        settings.get("message_ops")
        if isinstance(settings.get("message_ops"), dict)
        else {}
    )
    plugin_enabled = _bool_setting(plugins.get("auto_translate"), True)
    setting_enabled = _bool_setting(message_ops.get("auto_translate"), True)
    target_lang = str(
        message_ops.get("translation_target_language") or "zh-CN"
    ).strip()
    window_size = _window_size(message_ops.get("translation_context_window"))
    configured = bool(ai_configured)

    blocked_reason: str | None = None
    if not plugin_enabled:
        blocked_reason = "plugin_disabled"
    elif not setting_enabled:
        blocked_reason = "setting_disabled"
    elif not configured:
        blocked_reason = "ai_not_configured"
    elif target_lang != "zh-CN":
        blocked_reason = "unsupported_target_language"

    return AutoTranslationPolicy(
        enabled=blocked_reason is None,
        plugin_enabled=plugin_enabled,
        setting_enabled=setting_enabled,
        ai_configured=configured,
        target_lang=target_lang,
        window_size=window_size,
        blocked_reason=blocked_reason,
    )
