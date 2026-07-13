from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Callable

from .ai.provider import AIProviderError, WendingAIProvider
from .ai.service import AIService
from .config import AppConfig
from .language import (
    collapse_whitespace,
    dedupe_similar_lines,
    detect_preferred_language,
)
from .personas import resolve_persona
from .settings import AISettings
from .translation_memory import TranslationMemory


@dataclass(slots=True)
class RewriteResult:
    language: str
    message: str
    used_fallback: bool = False
    error: dict[str, object] | None = None
    persona: dict[str, str] | None = None


class Rewriter:
    def __init__(
        self,
        config: AppConfig,
        logger: Callable[..., None],
        *,
        ai_service: AIService | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        settings = getattr(config, "ai_settings", None) or AISettings.from_env()
        self.ai_service = ai_service or AIService(
            WendingAIProvider(settings),
            settings,
            audit_logger=logger,
        )
        self._translation_memory: TranslationMemory | None = None

    @property
    def translation_memory(self) -> TranslationMemory:
        if self._translation_memory is None:
            self._translation_memory = TranslationMemory(self.config.paths.memory_dir)
        return self._translation_memory

    @property
    def phrase_dict(self) -> dict[str, str]:
        """懒加载 LaoTalk 共享短语词典，用于 prompt 注入"""
        if not hasattr(self, "_phrase_dict"):
            self._phrase_dict: dict[str, str] = {}
            dict_path = os.environ.get(
                "LT_CORPUS_DICT",
                "/var/www/laotalk-beta/backend/shared_corpus/phrase_dict.json",
            )
            try:
                with open(dict_path, encoding="utf-8") as f:
                    self._phrase_dict = json.load(f)
            except Exception:
                pass
        return self._phrase_dict

    def _account_model(self) -> str | None:
        reply_settings = getattr(self.config, "web_settings", {}).get("reply") or {}
        return str(reply_settings.get("ai_model") or "").strip() or None

    def rewrite(
        self,
        target: dict,
        zh_text: str,
        memory_md: str,
        *,
        sidecar: dict | None = None,
        reply_overrides: dict | None = None,
    ) -> RewriteResult:
        persona = resolve_persona(
            str((reply_overrides or {}).get("persona_id") or ""),
            enabled=bool(
                (getattr(self.config, "web_settings", {}).get("plugins") or {}).get(
                    "persona_styles", True
                )
            ),
        )
        persona_metadata = persona.ui_metadata() if persona else None
        try:
            language, message = self._rewrite_with_model(
                target,
                zh_text,
                memory_md,
                sidecar=sidecar,
                reply_overrides=reply_overrides,
            )
            return RewriteResult(
                language=language,
                message=message,
                used_fallback=False,
                persona=persona_metadata,
            )
        except AIProviderError as exc:
            self.logger(
                "model_rewrite_failed",
                target=target.get("id"),
                error_code=exc.code,
                text_length=len(zh_text),
            )
            language, message = self._fallback(target, zh_text, memory_md)
            return RewriteResult(
                language=language,
                message=message,
                used_fallback=True,
                error=_provider_error_metadata(exc),
                persona=persona_metadata,
            )
        except Exception as exc:
            self.logger(
                "model_rewrite_failed",
                target=target.get("id"),
                error=str(exc),
                text_length=len(zh_text),
            )
            language, message = self._fallback(target, zh_text, memory_md)
            return RewriteResult(
                language=language,
                message=message,
                used_fallback=True,
                persona=persona_metadata,
            )

    def translate_only(self, target: dict, text: str, memory_md: str) -> RewriteResult:
        target_name = str(target.get("name") or "")
        target_language = detect_preferred_language(memory_md, target_name)
        if target_language == "user language":
            return RewriteResult(
                language="unchanged",
                message=collapse_whitespace(text),
                used_fallback=False,
            )
        try:
            message = self._translate_with_model(text, target_language)
            self._validate_output(message, target_language, text, allow_same=False)
            return RewriteResult(
                language=target_language, message=message, used_fallback=False
            )
        except AIProviderError as exc:
            self.logger(
                "model_translate_failed",
                target=target.get("id"),
                error_code=exc.code,
                text_length=len(text),
            )
            return RewriteResult(
                language=target_language,
                message=self._simple_translate_fallback(text, target_language),
                used_fallback=True,
                error=_provider_error_metadata(exc),
            )
        except Exception as exc:
            self.logger(
                "model_translate_failed",
                target=target.get("id"),
                error=str(exc),
                text_length=len(text),
            )
            return RewriteResult(
                language=target_language,
                message=self._simple_translate_fallback(text, target_language),
                used_fallback=True,
            )

    def translate_to_zh(self, text: str, source_lang: str) -> str:
        """Translate a single message into Chinese, returning the fallback text on failure."""
        return self.translate_to_zh_result(text, source_lang).message

    def translate_to_zh_result(self, text: str, source_lang: str) -> RewriteResult:
        """Translate to Chinese. Uses memory lookup first, then AI with self-learning."""
        text = collapse_whitespace(text or "").strip()
        if not text or source_lang == "Chinese":
            return RewriteResult(language="Chinese", message=text)

        # 1. Memory lookup
        cached = self.translation_memory.get(text, source_lang)
        if cached is not None:
            return RewriteResult(language="Chinese", message=cached)

        # 2. Hardcoded low-info patterns (also written to memory as confirmed)
        low_info_map = {
            "โดย": "嗯",
            "โอเค": "好的",
            "อืม": "嗯",
            "อือ": "嗯",
            "嗯嗯": "嗯嗯",
            "嗯": "嗯",
            "哦": "哦",
            "好": "好",
        }
        if text in low_info_map:
            zh = low_info_map[text]
            self.translation_memory.put(
                text, zh, source_lang, corrected=True, now=time.time()
            )
            return RewriteResult(language="Chinese", message=zh)

        # 3. AI translate
        try:
            # 注入 LaoTalk 共享短语词典（最近200条）
            phrase_dict = self.phrase_dict
            if phrase_dict:
                entries = list(phrase_dict.items())[:200]
                dict_section = "\n".join(f'  "{k}" → "{v}"' for k, v in entries)
                context_block = f"# 已知正确翻译（LaoTalk 用户反馈数据，共 {len(phrase_dict)} 条）\n{dict_section}\n\n"
            else:
                context_block = ""
            prompt = (
                "你是一个高精度的老挝语/泰语对话翻译。\n"
                "要求：\n"
                "1. 把下面聊天消息准确翻译成简体中文。\n"
                "2. 保持语气、情感、emoji。\n"
                + context_block
                + "3. 老挝语常见词：ເ = 伤心/难过，ເ = 明天，ເ = 要/带（留宿/陪伴），\n"
                "   ເ = 没赶上车，à = 起晚/睡懒觉，ໂ = 嗯（语气词）。\n"
                "4. 泰语常见词：ไม = 不/没（否定），เอ = 要/带走，ค้ = 过夜，รถ = 车，\n"
                "   ไม = 伤心/难受，ตื่น = 起床，สาย = 迟到/晚了。\n"
                '5. 1-2句话，不超过60字。只输出 JSON：{"zh":"..."}。\n\n'
                f"原文语言: {source_lang}\n"
                f"原文: {text}\n"
            )
            result = self.ai_service.chat(
                messages=[
                    {"role": "system", "content": "你只返回合法 JSON，准确翻译。"},
                    {"role": "user", "content": prompt},
                ],
                account_model=self._account_model(),
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(result.result.content)
            zh = collapse_whitespace(str(parsed.get("zh") or "").strip())
            if zh:
                # Write to memory, corrected=False (pending human review)
                self.translation_memory.put(
                    text, zh, source_lang, corrected=False, now=time.time()
                )
                return RewriteResult(language="Chinese", message=zh)
            return RewriteResult(language="Chinese", message=text)
        except AIProviderError as exc:
            self.logger(
                "auto_translate_failed",
                error_code=exc.code,
                text_length=len(text),
                source_lang=source_lang,
            )
            return RewriteResult(
                language="Chinese",
                message=text,
                used_fallback=True,
                error=_provider_error_metadata(exc),
            )
        except Exception as exc:
            self.logger(
                "auto_translate_failed",
                error=str(exc),
                text_length=len(text),
                source_lang=source_lang,
            )
            return RewriteResult(language="Chinese", message=text, used_fallback=True)

    def _rewrite_with_model(
        self,
        target: dict,
        zh_text: str,
        memory_md: str,
        *,
        sidecar: dict | None = None,
        reply_overrides: dict | None = None,
    ) -> tuple[str, str]:
        target_name = str(target.get("name") or "")
        target_language = detect_preferred_language(memory_md, target_name)
        reply_settings = self.config.web_settings.get("reply") or {}
        contact_model = (
            str((reply_overrides or {}).get("ai_model") or "").strip() or None
        )
        custom_prompt = str(
            (reply_overrides or {}).get("custom_system_prompt")
            or reply_settings.get("custom_system_prompt")
            or ""
        ).strip()
        default_style = str(reply_settings.get("default_reply_style") or "").strip()
        custom_style = str((reply_overrides or {}).get("reply_style") or "").strip()
        structured_style = ", ".join((sidecar or {}).get("response_style") or [])
        style_hint = "\n".join(
            x for x in [default_style, custom_style, structured_style] if x
        ).strip()
        system_content = "你只返回合法 JSON。像真人聊天，短句，不重复。"
        persona = resolve_persona(
            str((reply_overrides or {}).get("persona_id") or ""),
            enabled=bool(
                (getattr(self.config, "web_settings", {}).get("plugins") or {}).get(
                    "persona_styles", True
                )
            ),
        )
        if persona:
            system_content = f"{system_content}\n{persona.prompt}"
        if custom_prompt:
            system_content = f"{system_content}\n{custom_prompt}".strip()
        prompt = (
            "你负责把管理员输入改写成给目标用户的最终聊天消息。\n"
            "要求：\n"
            '1. 只输出 JSON：{"language":"...","message":"..."}\n'
            "2. message 必须是最终要发送的文本。\n"
            "3. 极短，最好 1 句话，通常不超过 18 个字或等效长度。\n"
            "4. 自然、像真人，不要解释，不要客套模板，不要重复。\n"
            "5. 如果对方只是回“嗯/好/ok/表情”，你的回复也要更短。\n"
            "6. 不要出现“我想说”“这是消息”“原文是”之类元话术。\n\n"
            f"目标用户: {target_name}\n"
            f"目标语言偏好: {target_language}\n"
            f"用户画像摘要:\n{memory_md[:1400]}\n\n"
            f"自定义回复风格:\n{style_hint or '无'}\n\n"
            f"管理员原文:\n{zh_text}\n"
        )
        result = self.ai_service.chat(
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            contact_model=contact_model,
            account_model=self._account_model(),
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(result.result.content)
        language = str(parsed.get("language") or "").strip() or target_language
        message = self._postprocess_message(str(parsed.get("message") or "").strip())
        self._validate_output(message, target_language, zh_text)
        return language, message

    def _translate_with_model(self, text: str, target_language: str) -> str:
        prompt = (
            "把下面内容翻译成目标语言，并保持自然、简短、可直接发送。\n"
            '只输出 JSON：{"message":"..."}\n'
            "尽量 1 句话，不要解释，不要重复。\n"
            f"目标语言: {target_language}\n"
            f"原文:\n{text}\n"
        )
        result = self.ai_service.chat(
            messages=[
                {"role": "system", "content": "你只返回合法 JSON。保持短句，不重复。"},
                {"role": "user", "content": prompt},
            ],
            account_model=self._account_model(),
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(result.result.content)
        return self._postprocess_message(str(parsed.get("message") or "").strip())

    def _postprocess_message(self, text: str) -> str:
        text = dedupe_similar_lines(text)
        text = collapse_whitespace(text)
        for prefix in [
            "ข้อความจากฉัน:",
            "ຂໍ້ຄວາມຈາກຂ້ອຍ:",
            "我想说：",
            "我想说:",
            "Message:",
        ]:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
        return text

    @staticmethod
    def _validate_output(
        message: str, expected_language: str, original_zh: str, allow_same: bool = False
    ) -> None:
        import re

        msg = (message or "").strip()
        if not msg:
            raise ValueError("empty rewritten message")
        if len(msg) > 48:
            raise ValueError("rewritten message too long")
        if not allow_same and msg == original_zh.strip():
            raise ValueError("rewritten message equals original Chinese")
        if "中文解释" in msg or "原中文" in msg or "message" in msg.lower():
            raise ValueError("rewritten message contains meta explanation")
        if "\n" in msg and len(msg.splitlines()) > 1:
            raise ValueError("rewritten message has too many lines")
        if msg.count("😊") + msg.count("🥺") + msg.count("😂") > 1:
            raise ValueError("too many emojis")
        chinese_chars = len(re.findall(r"[\u4E00-\u9FFF]", msg))
        lao_chars = len(re.findall(r"[\u0E80-\u0EFF]", msg))
        thai_chars = len(re.findall(r"[\u0E00-\u0E7F]", msg))
        if expected_language == "Lao" and lao_chars == 0:
            raise ValueError("expected Lao output but no Lao script found")
        if expected_language == "Thai" and thai_chars == 0:
            raise ValueError("expected Thai output but no Thai script found")
        if expected_language in {"Lao", "Thai"} and chinese_chars > max(
            1, len(msg) // 8
        ):
            raise ValueError("too much Chinese remained in rewritten output")

    @staticmethod
    def _simple_translate_fallback(text: str, target_language: str) -> str:
        clean = collapse_whitespace(text)
        if target_language == "Lao":
            return clean
        if target_language == "Thai":
            return clean
        return clean

    @staticmethod
    def _fallback(target: dict, zh_text: str, memory_md: str) -> tuple[str, str]:
        target_name = str(target.get("name") or "")
        preferred_lao = "Preferred language: Lao" in memory_md or "ເກຍ" in target_name
        clean = collapse_whitespace(zh_text)
        if preferred_lao:
            return "老挝语", clean
        if "Preferred language: Thai" in memory_md:
            return "泰语", clean
        return "中文", clean


def _provider_error_metadata(exc: AIProviderError) -> dict[str, object]:
    return {
        "code": exc.code,
        "retryable": exc.retryable,
        "request_id": exc.request_id,
    }
