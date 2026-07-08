from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig, load_json, save_json
from .language import approx_translate, summarize_mood
from .messaging import HermesMessenger
from .storage import EventLogger, StateDB


@dataclass(slots=True)
class ForwardState:
    last_message_id: int
    forwarded_pairs: list[str]


class AdminForwarder:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = StateDB(config.paths.db)
        self.logger = EventLogger(config.paths.log_dir / 'admin-forward.log')
        self.messenger = HermesMessenger(config)

    def load_state(self) -> ForwardState:
        payload = load_json(self.config.paths.forward_state, {'last_message_id': 0, 'forwarded_pairs': []})
        return ForwardState(last_message_id=int(payload.get('last_message_id', 0)), forwarded_pairs=list(payload.get('forwarded_pairs', [])))

    def save_state(self, state: ForwardState) -> None:
        save_json(self.config.paths.forward_state, {'last_message_id': state.last_message_id, 'forwarded_pairs': state.forwarded_pairs})

    def run(self) -> int:
        if not self.config.paths.db.exists():
            return 0
        state = self.load_state()
        rows = self.db.fetch_all_messages(state.last_message_id)
        if not rows:
            return 0

        origin_map = load_json(self.config.paths.sessions_json, {})
        origin_by_session = {}
        for rec in origin_map.values():
            sid = rec.get('session_id')
            if sid:
                origin_by_session[sid] = rec.get('origin') or {}

        pending_user: dict[str, dict] = {}
        forwarded_pairs = set(state.forwarded_pairs)
        max_id = state.last_message_id
        self.logger.log('scan_start', last_message_id=max_id, fetched=len(rows))

        for row in rows:
            max_id = max(max_id, int(row['id']))
            session_id = row['session_id']
            role = row['role']
            content = (row['content'] or '').strip()
            if not content:
                continue
            origin = origin_by_session.get(session_id, {})
            user_id = str(origin.get('user_id') or '').strip()
            user_name = str(origin.get('user_name') or origin.get('chat_name') or user_id or 'Unknown').strip()
            if user_id in self.config.admin_ids:
                continue
            if role == 'user':
                pending_user[session_id] = {
                    'message_id': int(row['id']),
                    'content': content,
                    'user_id': user_id,
                    'user_name': user_name,
                }
                continue
            if role != 'assistant':
                continue
            pending = pending_user.get(session_id)
            if not pending:
                continue
            pair_key = f"{pending['message_id']}->{int(row['id'])}"
            if pair_key in forwarded_pairs:
                continue

            admin_text = (
                '【WhatsApp聊天转发】\n'
                f"用户: {pending['user_name']}\n"
                f"用户ID: {pending['user_id']}\n"
                f"会话: {session_id}\n\n"
                f"1) 用户消息原文:\n{pending['content']}\n\n"
                f"2) 用户消息中文意思:\n{approx_translate(pending['content'])}\n\n"
                f"3) 发给用户的回复原文:\n{content}\n\n"
                f"4) 回复内容中文翻译:\n{approx_translate(content)}\n\n"
                f"5) 简短备注:\n{summarize_mood(pending['content'])}"
            )
            results = self.messenger.send_to_admin_channels(admin_text, kind='conversation_forward')
            if results and all(item.success for item in results):
                forwarded_pairs.add(pair_key)
                pending_user.pop(session_id, None)
                self.logger.log('forward_success', pair_key=pair_key, user_id=user_id, channels=len(results))
            else:
                self.logger.log('forward_failed', pair_key=pair_key, results=[{'success': r.success, 'stdout': r.stdout, 'stderr': r.stderr} for r in results])

        state.last_message_id = max_id
        state.forwarded_pairs = sorted(forwarded_pairs)[-500:]
        self.save_state(state)
        self.logger.log('scan_end', last_message_id=max_id, forwarded_count=len(state.forwarded_pairs))
        return 0
