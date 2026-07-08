from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
from typing import Any

from .config import AppConfig, load_json, save_json


@dataclass(slots=True)
class SendResult:
    success: bool
    chat_id: str
    stdout: str
    stderr: str
    payload: dict[str, Any]


class HermesMessenger:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def send(self, target: str, message: str, json_output: bool = True) -> SendResult:
        cmd = ["hermes", "--profile", self.config.paths.profile.name, "send", "--to", target]
        if json_output:
            cmd.append("--json")
        cmd.append(message)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        payload: dict[str, Any] = {}
        try:
            payload = json.loads((proc.stdout or "").strip() or "{}")
        except Exception:
            payload = {}
        success = proc.returncode == 0 and (not json_output or bool(payload.get("success", True)))
        chat_id = str(payload.get("chat_id") or "")
        return SendResult(success=success, chat_id=chat_id, stdout=proc.stdout, stderr=proc.stderr, payload=payload)

    def send_whatsapp(self, target_id: str, message: str, json_output: bool = True) -> SendResult:
        return self.send(f"whatsapp:{target_id}", message, json_output=json_output)

    def send_admin_text(self, message: str, kind: str = 'reply_ack') -> list[SendResult]:
        return self.send_to_admin_channels(message, kind=kind)

    def send_to_admin_channels(self, message: str, kind: str) -> list[SendResult]:
        results: list[SendResult] = []
        for channel in self.config.forwarding_channels:
            if not channel.get('enabled'):
                continue
            kinds = channel.get('kinds') or []
            if kind not in kinds:
                continue
            target = str(channel.get('target') or '').strip()
            if not target:
                continue
            results.append(self.send(target, message, json_output=False))
        return results


def normalize_name(value: str) -> str:
    value = (value or '').strip().lower()
    value = value.replace('❤️', '').replace('❤', '').replace('🤍', '')
    return re.sub(r"\s+", "", value)


def load_targets(config: AppConfig) -> list[dict[str, Any]]:
    payload = load_json(config.paths.channel_directory, {"platforms": {}})
    return list((payload.get("platforms") or {}).get("whatsapp") or [])


def refresh_aliases(config: AppConfig, targets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    existing = load_json(config.paths.alias_file, {})
    non_admin = [t for t in targets if str(t.get("id") or "") not in config.admin_ids]
    non_admin.sort(key=lambda t: (str(t.get("name") or ""), str(t.get("id") or "")))
    used_ids: set[str] = set()
    by_chat = {str(v.get("chat_id")): k for k, v in existing.items() if isinstance(v, dict) and v.get("chat_id")}
    aliases: dict[str, dict[str, Any]] = {}
    next_num = 1
    for target in non_admin:
        chat_id = str(target.get("id") or "")
        alias = by_chat.get(chat_id)
        if alias is None:
            while str(next_num) in used_ids or str(next_num) in existing:
                next_num += 1
            alias = str(next_num)
            next_num += 1
        used_ids.add(alias)
        aliases[alias] = {
            "chat_id": chat_id,
            "name": str(target.get("name") or ""),
            "type": target.get("type") or "dm",
        }
    save_json(config.paths.alias_file, aliases)
    return aliases


def resolve_target(target_text: str, targets: list[dict[str, Any]], aliases: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    raw = target_text.strip()
    norm = normalize_name(raw)
    if raw in aliases:
        alias = aliases[raw]
        return {"id": alias["chat_id"], "name": alias["name"], "type": alias.get("type", "dm"), "alias": raw}
    if raw.endswith("@lid") or raw.endswith("@s.whatsapp.net"):
        for target in targets:
            if target.get("id") == raw:
                return target
        return {"id": raw, "name": raw, "type": "dm"}
    scored: list[tuple[int, dict[str, Any]]] = []
    for target in targets:
        tid = str(target.get("id") or "")
        name = str(target.get("name") or "")
        nname = normalize_name(name)
        if raw == tid or raw == name or norm == nname:
            return target
        if norm and (norm in nname or nname in norm):
            scored.append((len(nname), target))
    if len(scored) == 1:
        return scored[0][1]
    if scored:
        scored.sort(key=lambda x: x[0])
        return scored[0][1]
    return None
