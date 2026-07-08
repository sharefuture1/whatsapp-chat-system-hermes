import json
import sqlite3

from whatsapp_chat_system.config import AppConfig
from whatsapp_chat_system.memory_refresh import MemoryRefresher
from whatsapp_chat_system.structured_profile import read_sidecar, write_sidecar

from conftest import create_profile, seed_conversation


def _build_app_config(profile):
    from whatsapp_chat_system.config import AppConfig
    return AppConfig.from_profile(str(profile))


def test_sidecar_written_during_refresh(tmp_path):
    profile = create_profile(tmp_path / 'p')
    seed_conversation(
        profile,
        user_id='u-side@lid',
        user_name='Side User',
        session_id='s-side',
        messages=[
            ('user', '我今天不舒服，累死了', 1700000100.0),
            ('assistant', '辛苦了', 1700000101.0),
        ],
    )
    cfg = _build_app_config(profile)
    MemoryRefresher(cfg).run()
    sidecar = read_sidecar('u-side@lid', profile / 'user-memory-md')
    assert sidecar is not None
    assert sidecar['preferred_language'] in ('Chinese', 'unknown')
    assert sidecar['priority'] == 'high'
    assert any('comfort' in s.lower() or 'vulnerable' in s.lower() for s in sidecar['sensitivities'])


def test_sidecar_read_falls_back_to_markdown_when_missing(tmp_path):
    profile = create_profile(tmp_path / 'p')
    seed_conversation(
        profile,
        user_id='u-fb@lid',
        user_name='FB User',
        session_id='s-fb',
        messages=[('user', '你好', 1700000200.0)],
    )
    cfg = _build_app_config(profile)
    MemoryRefresher(cfg).run()
    (profile / 'user-memory-md' / f"FB_User__u-fb@lid.json").unlink()
    sidecar = read_sidecar('u-fb@lid', profile / 'user-memory-md')
    assert sidecar is None


def test_sidecar_for_la_user(tmp_path):
    profile = create_profile(tmp_path / 'p')
    seed_conversation(
        profile,
        user_id='u-lo@lid',
        user_name='Lo User',
        session_id='s-lo',
        messages=[('user', 'ສະບາຍດີ', 1700000300.0), ('assistant', 'hello', 1700000301.0)],
    )
    cfg = _build_app_config(profile)
    MemoryRefresher(cfg).run()
    sidecar = read_sidecar('u-lo@lid', profile / 'user-memory-md')
    assert sidecar is not None
    assert sidecar['preferred_language'] == 'Lao'
