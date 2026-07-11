from whatsapp_chat_system.language import (
    approx_translate,
    detect_language,
    summarize_mood,
)


def test_detect_language():
    assert detect_language("你好") == "Chinese"
    assert detect_language("สวัสดี") == "Thai"
    assert detect_language("ສະບາຍດີ") == "Lao"


def test_approx_translate_low_info():
    result = approx_translate("โดย")
    assert "类似" in result and ("好" in result or "嗯" in result or "哦" in result)


def test_summarize_mood_health():
    assert "优先关怀" in summarize_mood("วันนี้ฉันรู้สึกฉันไม่สบาย")
