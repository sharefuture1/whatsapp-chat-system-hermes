"""Bounded language hints based only on customer input, not the UI locale."""

from __future__ import annotations

import re
from collections.abc import Iterable

_SCRIPTS = {
    "Lao": re.compile(r"[\u0e80-\u0eff]"),
    "Thai": re.compile(r"[\u0e00-\u0e7f]"),
    "Japanese": re.compile(r"[\u3040-\u30ff]"),
    "Korean": re.compile(r"[\uac00-\ud7af]"),
    "Chinese": re.compile(r"[\u4e00-\u9fff]"),
}
_ALIASES = {
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "chinese": "Chinese",
    "th": "Thai",
    "thai": "Thai",
    "lo": "Lao",
    "lao": "Lao",
    "en": "English/Latin",
    "english": "English/Latin",
    "vi": "Vietnamese",
    "vietnamese": "Vietnamese",
    "ja": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "korean": "Korean",
}
_ACK = re.compile(r"(?:ok|okay|555+|[\W\d_]+)", re.IGNORECASE)


def _hint(text: str) -> str | None:
    for language, pattern in _SCRIPTS.items():
        if pattern.search(text):
            return language
    return "English/Latin" if re.search(r"[A-Za-z]", text) else None


def reply_language(
    text: str, preference: str | None, recent_inbound: Iterable[str]
) -> str:
    value = (text or "").strip()
    # Short acknowledgements and emoji do not signal a language switch.
    if value and not _ACK.fullmatch(value):
        hint = _hint(value)
        if hint:
            return hint
    preferred = _ALIASES.get((preference or "").strip().lower())
    if preferred:
        return preferred
    for previous in reversed(list(recent_inbound)):
        if previous != text and not _ACK.fullmatch(previous.strip()):
            hint = _hint(previous)
            if hint:
                return hint
    return _hint(value) or "customer language"


def reply_language_instruction(language: str) -> str:
    if language == "English/Latin":
        rule = (
            "English/Latin script detected; use the exact language of the latest "
            "customer message, including Vietnamese when applicable."
        )
    else:
        rule = f"Reply language: {language}. Use this language for your reply."
    return (
        f"{rule} Do not switch to the operator's or page's language. "
        "Reply concisely to the latest customer message. Return only the reply text. "
        "Do not invent prices, opening hours, bookings or actions you did not take."
    )


def matches_reply_language(reply: str, language: str) -> bool:
    if not any(char.isalpha() for char in reply):
        return True
    pattern = _SCRIPTS.get(language)
    if pattern is None:
        return True  # Ambiguous Latin languages require model judgement, not guesses.
    expected = len(pattern.findall(reply))
    if not expected:
        return False
    other = sum(
        len(p.findall(reply))
        for name, p in _SCRIPTS.items()
        if name != language and not (language == "Japanese" and name == "Chinese")
    )
    return expected >= other
