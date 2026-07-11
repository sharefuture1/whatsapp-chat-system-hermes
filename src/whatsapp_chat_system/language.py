from __future__ import annotations

import re
from typing import Iterable

LOW_INFO_PATTERNS = [
    r"^\s*[😂🤣😄😁😊🥺❤️♥️🤍🙏👍]+\s*$",
    r"^\s*(ok|okay|โอเค|โดย|ໂດຍ|ครับ|ค่ะ|จ้า|อืม|อือ|嗯|嗯嗯|哦|好|555+|อืมๆ|ໂອເຄ|ຄັບ)\s*$",
]
CARE_PATTERNS = [
    r"ไม่สบาย",
    r"ບໍ່",
    r"เหนื่อย",
    r"ເ",
    r"ป่วย",
    r"เจ็บ",
    r"ปวด",
    r"不舒服",
    r"难受",
    r"生病",
    r"累",
    r"头疼",
    r"发烧",
]
AFFECTION_PATTERNS = [r"แฟน", r"คิดถึง", r"รอ", r"โทร", r"ເ", r"รัก", r"想你", r"等你"]


def detect_language(text: str) -> str:
    if not text:
        return "unknown"
    if re.search(r"[\u0E80-\u0EFF]", text):
        return "Lao"
    if re.search(r"[\u0E00-\u0E7F]", text):
        return "Thai"
    if re.search(r"[\u4E00-\u9FFF]", text):
        return "Chinese"
    if re.search(r"[A-Za-z]", text):
        return "English/Latin"
    return "unknown"


def is_low_info(text: str) -> bool:
    s = (text or "").strip()
    return (not s) or any(re.search(p, s, re.I) for p in LOW_INFO_PATTERNS)


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def dedupe_similar_lines(text: str) -> str:
    lines = [
        collapse_whitespace(x)
        for x in (text or "").splitlines()
        if collapse_whitespace(x)
    ]
    out = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return "\n".join(out)


def approx_translate(text: str) -> str:
    rules = [
        (r"ไม่สบาย|ບໍ", "在说自己不舒服/身体状态不好"),
        (r"เหนื่อย|ເ", "在说自己累了"),
        (r"กลับบ้าน", "在说回家/已经回家/准备回家"),
        (r"เลิกงาน", "在说下班了"),
        (r"คิดถ", "在表达想念/依恋"),
        (r"โทร", "在说之后会打电话/联系"),
        (r"ขอบคุ", "在表示感谢"),
        (r"โอเค|โด(?:ย)?", '语气性短回复，类似"好/嗯/哦"'),
    ]
    for pattern, meaning in rules:
        if re.search(pattern, text, re.I):
            return meaning
    return f"原文为{detect_language(text)}，需按上下文理解；整体是普通聊天内容。"


def summarize_mood(text: str) -> str:
    if re.search(r"ไม่สบาย|", text, re.I):
        return "用户状态偏脆弱/需要安抚，建议优先关怀。"
    if re.search(r"แฟน|", text, re.I):
        return "语气偏亲密暧昧，适合轻柔陪伴式回复。"
    if re.search(r"กลับ|", text, re.I):
        return "主要是在报备行程/动态，适合短回复加一句关心。"
    if re.search(r"โด|ໂ|โอ|😂|😊|🥺", text, re.I):
        return "这是低信息量维持聊天节奏的消息，回复宜短。"
    return "普通闲聊，保持自然简短即可。"


def detect_preferred_language(memory_md: str, target_name: str) -> str:
    if "Preferred language: Lao" in memory_md or "ເ" in target_name:
        return "Lao"
    if "Preferred language: Thai" in memory_md:
        return "Thai"
    return "user language"


def recent_languages(texts: Iterable[str]) -> list[str]:
    return [detect_language(t) for t in texts if (t or "").strip()]
