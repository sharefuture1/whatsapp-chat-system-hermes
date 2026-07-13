from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AppConfig, load_json, save_json
from .messaging import HermesMessenger, load_targets, refresh_aliases, resolve_target
from .parsing import BARE_IGNORE, INFO_COMMANDS, parse_command, parse_incomplete
from .rewriter import RewriteResult, Rewriter
from .storage import EventLogger, StateDB
from .structured_profile import read_sidecar


@dataclass(slots=True)
class RouterState:
    last_message_id: int
    handled_message_ids: list[int]
    last_command: str | None
    last_result: dict[str, Any] | None


class AdminRouter:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = StateDB(config.paths.db)
        self.logger = EventLogger(config.paths.log_dir / "admin-router.log")
        self.messenger = HermesMessenger(config)
        self.rewriter = Rewriter(config, self.logger.log)

    def load_state(self) -> RouterState:
        payload = load_json(
            self.config.paths.router_state,
            {
                "last_message_id": 0,
                "handled_message_ids": [],
                "last_command": None,
                "last_result": None,
            },
        )
        return RouterState(
            last_message_id=int(payload.get("last_message_id", 0)),
            handled_message_ids=[
                int(x) for x in payload.get("handled_message_ids", [])
            ],
            last_command=payload.get("last_command"),
            last_result=payload.get("last_result"),
        )

    def save_state(self, state: RouterState) -> None:
        save_json(
            self.config.paths.router_state,
            {
                "last_message_id": state.last_message_id,
                "handled_message_ids": state.handled_message_ids,
                "last_command": state.last_command,
                "last_result": state.last_result,
            },
        )

    @staticmethod
    def load_user_memory(config: AppConfig, target_id: str) -> str:
        for path in config.paths.memory_dir.glob(f"*__{target_id}.md"):
            return path.read_text()
        return ""

    @staticmethod
    def format_alias_list(aliases: dict[str, dict[str, Any]]) -> str:
        lines = ["当前联系人编号："]
        for alias, info in sorted(aliases.items(), key=lambda item: int(item[0])):
            lines.append(f"{alias} = {info.get('name')} ({info.get('chat_id')})")
        return "\n".join(lines)

    @staticmethod
    def format_status(state: RouterState, aliases: dict[str, dict[str, Any]]) -> str:
        last = state.last_result or {}
        lines = [
            "转发器状态：运行中",
            f"last_message_id: {state.last_message_id}",
            f"已知联系人数: {len(aliases)}",
        ]
        if last:
            lines.extend(
                [
                    f"最近命令: {last.get('command', '')}",
                    f"最近目标: {last.get('target_name', '')} ({last.get('target_id', '')})",
                    f"最近结果: {last.get('status', '')}",
                ]
            )
        return "\n".join(lines)

    def prepare_reply(
        self, target_text: str, message: str, mode: str = "direct"
    ) -> dict[str, Any]:
        targets = load_targets(self.config)
        aliases = refresh_aliases(self.config, targets)
        target = resolve_target(target_text, targets, aliases)
        if not target:
            raise ValueError("target_not_found")
        target_id = str(target.get("id") or "")
        memory_md = self.load_user_memory(self.config, target_id)
        sidecar = read_sidecar(target_id, self.config.paths.memory_dir) or {}
        reply_overrides = (
            (self.config.web_settings.get("reply") or {}).get("user_overrides") or {}
        ).get(target_id) or {}
        contact_profiles = self.config.web_settings.get("contact_profiles") or {}
        contact_profile = contact_profiles.get(target_id) or {}
        if contact_profile.get("persona_id") and not reply_overrides.get("persona_id"):
            reply_overrides = {
                **reply_overrides,
                "persona_id": contact_profile["persona_id"],
            }
        rewrite = self._rewrite_for_mode(
            target,
            message,
            memory_md,
            mode,
            sidecar=sidecar,
            reply_overrides=reply_overrides,
        )
        return {
            "target": target,
            "rewrite": rewrite,
            "memory_markdown": memory_md,
            "profile_sidecar": sidecar,
            "reply_overrides": reply_overrides,
        }

    def send_prepared_reply(
        self,
        target: dict[str, Any],
        rewrite: RewriteResult,
        source_text: str,
        mode: str,
    ) -> dict[str, Any]:
        send_result = self.messenger.send_whatsapp(
            str(target.get("id")), rewrite.message, json_output=True
        )
        send_ok = send_result.success and send_result.chat_id == str(target.get("id"))
        return {
            "success": send_ok,
            "chat_id": send_result.chat_id,
            "stdout": send_result.stdout,
            "stderr": send_result.stderr,
            "target": target,
            "rewrite": {
                "language": rewrite.language,
                "message": rewrite.message,
                "used_fallback": rewrite.used_fallback,
                "error": rewrite.error,
            },
            "mode": mode,
            "source_text": source_text,
            "message_id": send_result.payload.get("messageId")
            or send_result.payload.get("message_id"),
            "message_ids": send_result.payload.get("messageIds")
            or send_result.payload.get("message_ids")
            or [],
        }

    def _rewrite_for_mode(
        self,
        target: dict[str, Any],
        message: str,
        memory_md: str,
        mode: str,
        *,
        sidecar: dict[str, Any] | None = None,
        reply_overrides: dict[str, Any] | None = None,
    ) -> RewriteResult:
        if mode == "smart":
            return self.rewriter.rewrite(
                target,
                self._truncate(
                    message,
                    int(self.config.web_settings["reply"]["smart_max_length"] * 2),
                ),
                memory_md,
                sidecar=sidecar,
                reply_overrides=reply_overrides,
            )
        if mode == "translate":
            return self.rewriter.translate_only(
                target,
                self._truncate(
                    message,
                    int(self.config.web_settings["reply"]["translate_max_length"] * 2),
                ),
                memory_md,
            )
        return RewriteResult(
            language="direct", message=self._truncate(message, 500), used_fallback=False
        )

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        text = (text or "").strip()
        return text if len(text) <= limit else text[:limit].rstrip()

    def run(self) -> int:
        if not self.config.paths.db.exists():
            return 0
        state = self.load_state()
        rows = self.db.fetch_admin_messages(
            state.last_message_id, self.config.admin_ids
        )
        handled = set(state.handled_message_ids)
        targets = load_targets(self.config)
        aliases = refresh_aliases(self.config, targets)
        max_id = state.last_message_id
        self.logger.log("scan_start", last_message_id=max_id, fetched=len(rows))

        for row in rows:
            rid = int(row["id"])
            max_id = max(max_id, rid)
            text = (row["content"] or "").strip()
            if rid in handled:
                continue
            if text in BARE_IGNORE:
                self.logger.log("ignored_bare_token", message_id=rid, text=text)
                continue
            if text in INFO_COMMANDS:
                msg = (
                    self.format_alias_list(aliases)
                    if text
                    in {"联系人列表", "联系人编号", "别名列表", "alias", "aliases"}
                    else self.format_status(state, aliases)
                )
                self.messenger.send_admin_text(msg, kind="system_alert")
                handled.add(rid)
                self.logger.log("info_command", message_id=rid, text=text)
                continue
            incomplete_target = parse_incomplete(text)
            if incomplete_target:
                self.messenger.send_admin_text(
                    f"目标已识别为 {incomplete_target}，请继续发送完整格式：发给 {incomplete_target}：内容",
                    kind="reply_ack",
                )
                handled.add(rid)
                self.logger.log(
                    "incomplete_command", message_id=rid, target=incomplete_target
                )
                continue

            parsed = parse_command(text)
            if not parsed:
                continue

            target = resolve_target(parsed["target"], targets, aliases)
            state.last_command = text
            if not target:
                self.messenger.send_admin_text(
                    f"未找到目标用户：{parsed['target']}。请检查名字、ID，或先发送“联系人编号”查看列表。",
                    kind="reply_ack",
                )
                handled.add(rid)
                state.last_result = {"command": text, "status": "target_not_found"}
                self.logger.log(
                    "target_not_found", message_id=rid, target=parsed["target"]
                )
                continue

            target_id = str(target.get("id") or "")
            memory_md = self.load_user_memory(self.config, target_id)
            sidecar = read_sidecar(target_id, self.config.paths.memory_dir) or {}
            reply_overrides = (
                (self.config.web_settings.get("reply") or {}).get("user_overrides")
                or {}
            ).get(target_id) or {}
            contact_profiles = self.config.web_settings.get("contact_profiles") or {}
            contact_profile = contact_profiles.get(target_id) or {}
            if contact_profile.get("persona_id") and not reply_overrides.get(
                "persona_id"
            ):
                reply_overrides = {
                    **reply_overrides,
                    "persona_id": contact_profile["persona_id"],
                }
            rewrite = self.rewriter.rewrite(
                target,
                parsed["message"],
                memory_md,
                sidecar=sidecar,
                reply_overrides=reply_overrides,
            )
            result = self.send_prepared_reply(
                target, rewrite, parsed["message"], mode="smart"
            )
            send_ok = result["success"]
            alias_suffix = (
                f"\n数字ID: {target.get('alias')}" if target.get("alias") else ""
            )
            if send_ok:
                ack = (
                    f"已发送给 {target.get('name') or target.get('id')}\n"
                    f"目标ID: {target.get('id')}{alias_suffix}\n"
                    f"识别语言: {rewrite.language}\n"
                    f"原中文: {parsed['message']}\n"
                    f"实际发送: {rewrite.message}"
                )
                self.messenger.send_admin_text(ack, kind="reply_ack")
                state.last_result = {
                    "command": text,
                    "target_name": target.get("name"),
                    "target_id": target.get("id"),
                    "status": "sent",
                    "language": rewrite.language,
                    "message": rewrite.message,
                    "used_fallback": rewrite.used_fallback,
                }
                self.logger.log(
                    "send_success",
                    message_id=rid,
                    target=target.get("id"),
                    alias=target.get("alias"),
                    language=rewrite.language,
                    final_text=rewrite.message,
                )
            else:
                ack = (
                    f"发送失败：{target.get('name') or target.get('id')}\n"
                    f"目标ID: {target.get('id')}{alias_suffix}\n"
                    f"原中文: {parsed['message']}\n"
                    f"准备发送: {rewrite.message}\n"
                    f"返回: {(result['stdout'] or result['stderr']).strip()}"
                )
                self.messenger.send_admin_text(ack, kind="system_alert")
                state.last_result = {
                    "command": text,
                    "target_name": target.get("name"),
                    "target_id": target.get("id"),
                    "status": "failed",
                }
                self.logger.log(
                    "send_failed",
                    message_id=rid,
                    target=target.get("id"),
                    stdout=result["stdout"],
                    stderr=result["stderr"],
                )
            handled.add(rid)

        state.last_message_id = max_id
        state.handled_message_ids = sorted(handled)[-500:]
        self.save_state(state)
        self.logger.log(
            "scan_end",
            last_message_id=max_id,
            handled_count=len(state.handled_message_ids),
        )
        return 0
