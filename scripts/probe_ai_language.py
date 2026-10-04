"""Synthetic live-AI smoke test. Never touches WhatsApp accounts or sends messages."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from whatsapp_chat_system.ai.crypto import decrypt_api_key
    from whatsapp_chat_system.ai.provider import AIProviderError, WendingAIProvider
    from whatsapp_chat_system.ai.reply_language import (
        matches_reply_language,
        reply_language,
        reply_language_instruction,
    )
    from whatsapp_chat_system.settings import AISettings

    env_file = Path("/etc/whatsapp-chat-system/api.env")
    for line in env_file.read_text().splitlines():
        name, separator, value = line.partition("=")
        if separator and name == "AI_SECRET_ENCRYPTION_KEY":
            os.environ[name] = value.strip().strip("\"'")
    with sqlite3.connect(
        "file:/var/lib/whatsapp-chat-system/api/app.db?mode=ro", uri=True
    ) as connection:
        row = connection.execute(
            "SELECT base_url, default_model, api_key_ciphertext "
            "FROM ai_runtime_settings WHERE id = ?",
            ("global",),
        ).fetchone()
    if not row:
        print(json.dumps({"ok": False, "code": "ai_not_configured"}))
        return 2
    provider = WendingAIProvider(
        AISettings(
            base_url=row[0],
            api_key=decrypt_api_key(row[2]),
            default_model=row[1],
            timeout_seconds=35,
            max_retries=0,
        )
    )
    samples = [
        ("Thai", "สวัสดีครับ อยากสอบถามวิธีจองครับ"),
        ("Lao", "ສະບາຍດີ ຂ້ອຍຢາກສອບຖາມຂໍ້ມູນ"),
        ("Chinese", "你好，我想了解怎样预约。"),
        ("English/Latin", "Hello, how can I make a booking?"),
    ]
    failures = 0
    try:
        for expected, text in samples:
            language = reply_language(text, None, [])
            try:
                result = provider.chat(
                    model=row[1],
                    messages=[
                        {
                            "role": "system",
                            "content": reply_language_instruction(language),
                        },
                        {"role": "user", "content": text},
                    ],
                )
                ok = bool(result.content.strip()) and matches_reply_language(
                    result.content, expected
                )
                failures += not ok
                print(
                    json.dumps(
                        {
                            "test": "synthetic_reply",
                            "language": language,
                            "ok": ok,
                            "latency_ms": result.latency_ms,
                            "reply": result.content,
                        },
                        ensure_ascii=False,
                    )
                )
            except AIProviderError as error:
                failures += 1
                print(
                    json.dumps(
                        {
                            "test": "synthetic_reply",
                            "language": language,
                            "ok": False,
                            "code": error.code,
                        }
                    )
                )
        try:
            result = provider.chat(
                model=row[1],
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "Translate each input faithfully into Simplified Chinese. Return JSON with keys th, lo, en. Do not answer the questions.",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "th": samples[0][1],
                                "lo": samples[1][1],
                                "en": samples[3][1],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
            translated = json.loads(result.content)
            ok = all(
                isinstance(translated.get(key), str)
                and translated[key].strip()
                and matches_reply_language(translated[key], "Chinese")
                for key in ("th", "lo", "en")
            )
            failures += not ok
            print(
                json.dumps(
                    {
                        "test": "synthetic_translation",
                        "ok": ok,
                        "latency_ms": result.latency_ms,
                        "translated": translated,
                    },
                    ensure_ascii=False,
                )
            )
        except (AIProviderError, ValueError, TypeError) as error:
            failures += 1
            print(
                json.dumps(
                    {
                        "test": "synthetic_translation",
                        "ok": False,
                        "code": getattr(error, "code", "invalid_result"),
                    }
                )
            )
    finally:
        provider.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
