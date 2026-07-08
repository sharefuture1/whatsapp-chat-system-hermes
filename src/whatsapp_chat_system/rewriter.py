from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import requests

from .config import AppConfig
from .language import collapse_whitespace, dedupe_similar_lines, detect_preferred_language


@dataclass(slots=True)
class RewriteResult:
    language: str
    message: str
    used_fallback: bool = False


class Rewriter:
    def __init__(self, config: AppConfig, logger: Callable[..., None]) -> None:
        self.config = config
        self.logger = logger

    def rewrite(self, target: dict, zh_text: str, memory_md: str) -> RewriteResult:
        try:
            language, message = self._rewrite_with_model(target, zh_text, memory_md)
            return RewriteResult(language=language, message=message, used_fallback=False)
        except Exception as exc:
            self.logger('model_rewrite_failed', target=target.get('id'), error=str(exc), text=zh_text)
            language, message = self._fallback(target, zh_text, memory_md)
            return RewriteResult(language=language, message=message, used_fallback=True)

    def translate_only(self, target: dict, text: str, memory_md: str) -> RewriteResult:
        target_name = str(target.get('name') or '')
        target_language = detect_preferred_language(memory_md, target_name)
        if target_language == 'user language':
            return RewriteResult(language='unchanged', message=collapse_whitespace(text), used_fallback=False)
        try:
            message = self._translate_with_model(text, target_language)
            self._validate_output(message, target_language, text, allow_same=False)
            return RewriteResult(language=target_language, message=message, used_fallback=False)
        except Exception as exc:
            self.logger('model_translate_failed', target=target.get('id'), error=str(exc), text=text)
            return RewriteResult(language=target_language, message=self._simple_translate_fallback(text, target_language), used_fallback=True)

    def _rewrite_with_model(self, target: dict, zh_text: str, memory_md: str) -> tuple[str, str]:
        target_name = str(target.get('name') or '')
        target_language = detect_preferred_language(memory_md, target_name)
        prompt = (
            '你负责把管理员输入改写成给目标用户的最终聊天消息。\n'
            '要求：\n'
            '1. 只输出 JSON：{"language":"...","message":"..."}\n'
            '2. message 必须是最终要发送的文本。\n'
            '3. 极短，最好 1 句话，通常不超过 18 个字或等效长度。\n'
            '4. 自然、像真人，不要解释，不要客套模板，不要重复。\n'
            '5. 如果对方只是回“嗯/好/ok/表情”，你的回复也要更短。\n'
            '6. 不要出现“我想说”“这是消息”“原文是”之类元话术。\n\n'
            f'目标用户: {target_name}\n'
            f'目标语言偏好: {target_language}\n'
            f'用户画像摘要:\n{memory_md[:1400]}\n\n'
            f'管理员原文:\n{zh_text}\n'
        )
        payload = {
            'model': self.config.model['model'],
            'messages': [
                {'role': 'system', 'content': '你只返回合法 JSON。像真人聊天，短句，不重复。'},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.2,
            'response_format': {'type': 'json_object'},
        }
        response = requests.post(
            f"{self.config.model['base_url'].rstrip('/')}/chat/completions",
            headers={'Authorization': f"Bearer {self.config.model['api_key']}", 'Content-Type': 'application/json'},
            json=payload,
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        content = data['choices'][0]['message']['content']
        parsed = json.loads(content)
        language = str(parsed.get('language') or '').strip() or target_language
        message = self._postprocess_message(str(parsed.get('message') or '').strip())
        self._validate_output(message, target_language, zh_text)
        return language, message

    def _translate_with_model(self, text: str, target_language: str) -> str:
        prompt = (
            '把下面内容翻译成目标语言，并保持自然、简短、可直接发送。\n'
            '只输出 JSON：{"message":"..."}\n'
            '尽量 1 句话，不要解释，不要重复。\n'
            f'目标语言: {target_language}\n'
            f'原文:\n{text}\n'
        )
        payload = {
            'model': self.config.model['model'],
            'messages': [
                {'role': 'system', 'content': '你只返回合法 JSON。保持短句，不重复。'},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.1,
            'response_format': {'type': 'json_object'},
        }
        response = requests.post(
            f"{self.config.model['base_url'].rstrip('/')}/chat/completions",
            headers={'Authorization': f"Bearer {self.config.model['api_key']}", 'Content-Type': 'application/json'},
            json=payload,
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        content = data['choices'][0]['message']['content']
        parsed = json.loads(content)
        return self._postprocess_message(str(parsed.get('message') or '').strip())

    def _postprocess_message(self, text: str) -> str:
        text = dedupe_similar_lines(text)
        text = collapse_whitespace(text)
        for prefix in ['ข้อความจากฉัน:', 'ຂໍ້ຄວາມຈາກຂ້ອຍ:', '我想说：', '我想说:', 'Message:']:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        return text

    @staticmethod
    def _validate_output(message: str, expected_language: str, original_zh: str, allow_same: bool = False) -> None:
        import re

        msg = (message or '').strip()
        if not msg:
            raise ValueError('empty rewritten message')
        if len(msg) > 48:
            raise ValueError('rewritten message too long')
        if not allow_same and msg == original_zh.strip():
            raise ValueError('rewritten message equals original Chinese')
        if '中文解释' in msg or '原中文' in msg or 'message' in msg.lower():
            raise ValueError('rewritten message contains meta explanation')
        if '\n' in msg and len(msg.splitlines()) > 1:
            raise ValueError('rewritten message has too many lines')
        if msg.count('😊') + msg.count('🥺') + msg.count('😂') > 1:
            raise ValueError('too many emojis')
        chinese_chars = len(re.findall(r'[\u4E00-\u9FFF]', msg))
        lao_chars = len(re.findall(r'[\u0E80-\u0EFF]', msg))
        thai_chars = len(re.findall(r'[\u0E00-\u0E7F]', msg))
        if expected_language == 'Lao' and lao_chars == 0:
            raise ValueError('expected Lao output but no Lao script found')
        if expected_language == 'Thai' and thai_chars == 0:
            raise ValueError('expected Thai output but no Thai script found')
        if expected_language in {'Lao', 'Thai'} and chinese_chars > max(1, len(msg) // 8):
            raise ValueError('too much Chinese remained in rewritten output')

    @staticmethod
    def _simple_translate_fallback(text: str, target_language: str) -> str:
        clean = collapse_whitespace(text)
        if target_language == 'Lao':
            return clean
        if target_language == 'Thai':
            return clean
        return clean

    @staticmethod
    def _fallback(target: dict, zh_text: str, memory_md: str) -> tuple[str, str]:
        target_name = str(target.get('name') or '')
        preferred_lao = 'Preferred language: Lao' in memory_md or 'ເກຍ' in target_name
        clean = collapse_whitespace(zh_text)
        if preferred_lao:
            return '老挝语', clean
        if 'Preferred language: Thai' in memory_md:
            return '泰语', clean
        return '中文', clean
