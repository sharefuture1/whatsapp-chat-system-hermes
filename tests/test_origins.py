import json
import time

from whatsapp_chat_system.origins import OriginsCache


def test_origins_cache_returns_parsed_data(tmp_path):
    p = tmp_path / 'sessions.json'
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({
        'k1': {'session_id': 's1', 'origin': {'user_id': 'u1', 'user_name': 'User One'}},
        'k2': {'session_id': 's2', 'origin': {'user_id': 'u2'}},
    }))
    cache = OriginsCache(ttl_seconds=60)
    data = cache.load(p)
    assert data['s1']['user_name'] == 'User One'
    assert data['s2']['user_id'] == 'u2'


def test_origins_cache_invalidates_on_mtime(tmp_path):
    p = tmp_path / 'sessions.json'
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({'k1': {'session_id': 's1', 'origin': {'user_id': 'u1'}}}))
    cache = OriginsCache(ttl_seconds=60)
    data1 = cache.load(p)
    assert data1 == {'s1': {'user_id': 'u1'}}
    time.sleep(1.05)
    p.write_text(json.dumps({'k1': {'session_id': 's1', 'origin': {'user_id': 'u1-v2'}}}))
    data2 = cache.load(p)
    assert data2['s1']['user_id'] == 'u1-v2'


def test_origins_cache_handles_missing_file(tmp_path):
    p = tmp_path / 'missing.json'
    cache = OriginsCache(ttl_seconds=60)
    assert cache.load(p) == {}


def test_origins_cache_skips_records_without_session_id(tmp_path):
    p = tmp_path / 'sessions.json'
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({
        'k1': {'session_id': 's1', 'origin': {'user_id': 'u1'}},
        'k2': {'origin': {'user_id': 'u2'}},
    }))
    cache = OriginsCache(ttl_seconds=60)
    data = cache.load(p)
    assert 's1' in data
    assert 's2' not in data
