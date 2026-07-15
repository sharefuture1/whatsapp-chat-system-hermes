from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(slots=True)
class LaoTalkTranslateResult:
    ok: bool
    translated: str | None
    error: str | None = None


def laotalk_translate(text: str, source_lang: str, target_lang: str = 'zh') -> LaoTalkTranslateResult:
    clean = (text or '').strip()
    if not clean:
        return LaoTalkTranslateResult(ok=True, translated='')

    base = os.environ.get('LT_TRANSLATE_URL', 'http://127.0.0.1:3020/api/translate').strip() or 'http://127.0.0.1:3020/api/translate'
    src = 'auto'
    if source_lang == 'Lao':
        src = 'lo'
    elif source_lang == 'Thai':
        src = 'th'
    elif source_lang in {'Latin', 'Unknown'}:
        src = 'auto'
    elif source_lang == 'Chinese':
        src = 'zh'
    query = urllib.parse.urlencode({'text': clean, 'src': src, 'dst': target_lang})
    url = f"{base}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            raw = resp.read().decode('utf-8', 'ignore')
        payload = json.loads(raw)
        translated = str(payload.get('result') or '').strip()
        if not translated:
            return LaoTalkTranslateResult(ok=False, translated=None, error='empty_result')
        return LaoTalkTranslateResult(ok=True, translated=translated)
    except Exception as exc:
        return LaoTalkTranslateResult(ok=False, translated=None, error=str(exc))
