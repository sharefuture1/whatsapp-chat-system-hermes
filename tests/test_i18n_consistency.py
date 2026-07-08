"""Test that every i18n key used in components is present in the dictionaries."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


WEB_SRC = Path(__file__).resolve().parent.parent / 'web' / 'src'


def _extract_keys_from_file(path: Path) -> set[str]:
    text = path.read_text()
    keys: set[str] = set()
    pattern = re.compile(r"\bt\(\s*['\"]([a-zA-Z][a-zA-Z0-9_]*)['\"]")
    keys.update(pattern.findall(text))
    nav_pattern = re.compile(r"t\(`nav([A-Z][a-zA-Z]+)`\)")
    for match in nav_pattern.findall(text):
        keys.add(f'nav{match}')
    return keys


def _load_dict_keys() -> dict[str, set[str]]:
    src = (WEB_SRC / 'i18n.js').read_text()
    en_match = re.search(r"en:\s*\{(.*?)\n\s*\},", src, re.S)
    zh_match = re.search(r"zh:\s*\{(.*?)\n\s*\},", src, re.S)
    th_match = re.search(r"th:\s*\{(.*?)\n\s*\},", src, re.S)
    lo_match = re.search(r"lo:\s*\{(.*?)\n\s*\},", src, re.S)
    if not (en_match and zh_match and th_match and lo_match):
        return {}
    out = {}
    for lang, match in (('en', en_match), ('zh', zh_match), ('th', th_match), ('lo', lo_match)):
        keys = set(re.findall(r"^\s*([a-zA-Z][a-zA-Z0-9]*):", match.group(1), re.M))
        out[lang] = keys
    return out


def test_i18n_dicts_have_same_keys():
    dicts = _load_dict_keys()
    assert dicts, 'failed to load i18n dictionaries'
    base = dicts['en']
    for lang, keys in dicts.items():
        missing = base - keys
        extra = keys - base
        assert not missing, f'lang {lang} missing keys: {sorted(missing)}'
        assert not extra, f'lang {lang} has extra keys: {sorted(extra)}'


def test_all_t_keys_exist_in_dict():
    dicts = _load_dict_keys()
    en = dicts.get('en', set())
    if not en:
        pytest.skip('i18n dictionaries not parseable')
    referenced: set[str] = set()
    for path in WEB_SRC.rglob('*.jsx'):
        if 'components' not in str(path):
            continue
        referenced.update(_extract_keys_from_file(path))
    referenced.update(_extract_keys_from_file(WEB_SRC / 'App.jsx'))
    missing = referenced - en
    assert not missing, f'i18n keys used in components but missing: {sorted(missing)}'
