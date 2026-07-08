"""Helpers for building isolated profile fixtures in tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from whatsapp_chat_system.config import build_password_record, default_web_settings, save_json


def create_profile(root: Path, *, password: str = 'test-pass', admin_channels: list | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'sessions').mkdir(exist_ok=True)
    (root / 'logs').mkdir(exist_ok=True)
    (root / 'user-memory-md').mkdir(exist_ok=True)
    (root / 'channel_directory.json').write_text('{}')
    (root / 'user-aliases.json').write_text('{}')
    settings = default_web_settings()
    settings['auth'] = build_password_record(password)
    save_json(root / 'web-settings.json', settings)
    if admin_channels is None:
        admin_channels = [
            {
                'id': 'default-whatsapp-admin',
                'name': 'WhatsApp Admin',
                'platform': 'whatsapp',
                'target': 'whatsapp:test-admin@lid',
                'enabled': True,
                'kinds': ['reply_ack', 'conversation_forward', 'system_alert'],
            }
        ]
    save_json(root / 'admin-channels.json', admin_channels)
    (root / '.admin-command-router-state.json').write_text(json.dumps({'last_message_id': 0, 'processed_ids': []}))
    (root / '.admin-forward-state.json').write_text(json.dumps({'last_message_id': 0, 'forwarded_pairs': []}))
    db_path = root / 'state.db'
    conn = sqlite3.connect(db_path)
    conn.executescript(
        '''
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            title TEXT,
            started_at REAL,
            source TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp REAL
        );
        '''
    )
    conn.commit()
    conn.close()
    return root


def seed_conversation(
    profile: Path,
    *,
    user_id: str,
    user_name: str,
    session_id: str,
    messages: list[tuple[str, str, float]],
) -> None:
    db = sqlite3.connect(profile / 'state.db')
    db.execute(
        'INSERT INTO sessions(id, user_id, title, started_at, source) VALUES (?, ?, ?, ?, ?)',
        (session_id, user_id, user_name, messages[0][2], 'whatsapp'),
    )
    db.executemany(
        'INSERT INTO messages(session_id, role, content, timestamp) VALUES (?, ?, ?, ?)',
        [(session_id, role, content, ts) for role, content, ts in messages],
    )
    db.commit()
    db.close()
    origins_path = profile / 'sessions' / 'sessions.json'
    origins = json.loads(origins_path.read_text() or '{}') if origins_path.exists() else {}
    origins[session_id] = {
        'session_id': session_id,
        'origin': {'user_id': user_id, 'user_name': user_name, 'chat_name': user_name},
    }
    origins_path.write_text(json.dumps(origins, ensure_ascii=False, indent=2))
