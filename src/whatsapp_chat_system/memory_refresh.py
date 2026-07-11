from __future__ import annotations

import datetime as dt
import re

from .config import AppConfig, load_json
from .profile import render_md, summarize_user_messages
from .storage import StateDB
from .structured_profile import write_sidecar


class MemoryRefresher:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = StateDB(config.paths.db)

    @staticmethod
    def safe_name(name: str) -> str:
        return re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_')[:60] or 'user'

    def run(self) -> int:
        if not self.config.paths.db.exists():
            return 0
        sessions = self.db.fetch_sessions()
        rows = self.db.fetch_session_messages()
        origins_raw = load_json(self.config.paths.sessions_json, {})
        origins = {}
        for _session_key, rec in origins_raw.items():
            sid = rec.get('session_id')
            if sid:
                origins[sid] = rec.get('origin') or {}

        by_user: dict[str, dict] = {}
        for msg in rows:
            sid = msg['session_id']
            sess = sessions.get(sid, {})
            origin = origins.get(sid, {})
            user_id = (sess.get('user_id') or origin.get('user_id') or '').strip()
            if not user_id:
                continue
            user_name = (origin.get('user_name') or origin.get('chat_name') or user_id).strip()
            entry = by_user.setdefault(user_id, {
                'user_name': user_name,
                'session_ids': [],
                'first_ts': msg['timestamp'],
                'last_ts': msg['timestamp'],
                'user_msgs': [],
                'assistant_msgs': [],
            })
            if sid not in entry['session_ids']:
                entry['session_ids'].append(sid)
            entry['first_ts'] = min(entry['first_ts'], msg['timestamp'])
            entry['last_ts'] = max(entry['last_ts'], msg['timestamp'])
            content = (msg['content'] or '').strip()
            if not content:
                continue
            if msg['role'] == 'user':
                if content.startswith('[System note:'):
                    continue
                entry['user_msgs'].append(content)
            elif msg['role'] == 'assistant':
                if '记住你喜欢' in content or 'บันทึกไม่สำเร็จ' in content or 'พื้นที่ความจำเต็ม' in content:
                    continue
                entry['assistant_msgs'].append(content)

        for user_id, info in by_user.items():
            profile = summarize_user_messages(info['user_msgs'])
            role_label = 'admin' if user_id in self.config.admin_ids else 'regular user'
            rendered = render_md(
                user_name=info['user_name'],
                user_id=user_id,
                role_label=role_label,
                first_seen=dt.datetime.fromtimestamp(info['first_ts'], dt.UTC).isoformat(),
                last_seen=dt.datetime.fromtimestamp(info['last_ts'], dt.UTC).isoformat(),
                session_ids=info['session_ids'],
                profile=profile,
                recent_user_msgs=info['user_msgs'],
                recent_assistant_msgs=info['assistant_msgs'],
            )
            filename = f"{self.safe_name(info['user_name'])}__{user_id}.md"
            memory_path = self.config.paths.memory_dir / filename
            memory_path.write_text(rendered)
            write_sidecar(memory_path, profile)
        return 0
