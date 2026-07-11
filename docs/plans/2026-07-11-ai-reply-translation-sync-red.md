# Legacy delta cache-only translation RED

关联规格：`SDD-P1-05`

## 真实命令

```bash
./.venv/bin/pytest -q tests/test_translation.py -k 'legacy_delta_translation'
```

## 核心失败

```text
FAILED test_legacy_delta_translation_cache_miss_does_not_call_provider
FAILED test_legacy_delta_translation_returns_cached_value_without_provider

src/whatsapp_chat_system/web_api.py:1014
    messages = _attach_translations(config, user_id, messages)
src/whatsapp_chat_system/web_api.py:534
    _ensure_message_translations(config, user_id, messages)
src/whatsapp_chat_system/web_api.py:488
    zh = worker.translate_to_zh(content, source_lang)

2 failed, 10 deselected, 1 warning in 6.07s
```

结论：Legacy delta GET 当前会进入缺失译文生成路径并同步调用翻译 worker，不符合 cache-only 契约。
