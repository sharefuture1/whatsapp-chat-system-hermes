from __future__ import annotations

import re

COMMAND_PATTERNS = [
    r'^\s*发给\s*(?P<target>[^：:]+)\s*[：:]\s*(?P<message>.+?)\s*$',
    r'^\s*代发给\s*(?P<target>[^：:]+)\s*[：:]\s*(?P<message>.+?)\s*$',
    r'^\s*用对方的语言发给\s*(?P<target>[^：:]+)\s*[：:]\s*(?P<message>.+?)\s*$',
    r'^\s*翻译并发给\s*(?P<target>[^：:]+)\s*[：:]\s*(?P<message>.+?)\s*$',
    r'^\s*发给\s+(?P<target>\S+)\s+(?P<message>.+?)\s*$',
    r'^\s*代发给\s+(?P<target>\S+)\s+(?P<message>.+?)\s*$',
]
INCOMPLETE_PATTERNS = [
    r'^\s*发给\s+(?P<target>[^：:]+)\s*[：]\s*$',
    r'^\s*发给\s+(?P<target>[^：:]+)\s*$'
]
INFO_COMMANDS = {'联系人列表', '联系人编号', '别名列表', 'alias', 'aliases', '转发状态', 'router状态', 'router status', 'status'}
BARE_IGNORE = {'1', '2', 'david', 'David', 'ເກຍ', 'ເກຍ❤️'}


def parse_command(text: str) -> dict[str, str] | None:
    for pattern in COMMAND_PATTERNS:
        match = re.match(pattern, text, re.S)
        if match:
            return {'target': match.group('target').strip(), 'message': match.group('message').strip()}
    return None


def parse_incomplete(text: str) -> str | None:
    for pattern in INCOMPLETE_PATTERNS:
        match = re.match(pattern, text, re.S)
        if match:
            return match.group('target').strip()
    return None
