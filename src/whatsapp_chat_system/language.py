from __future__ import annotations

import re
from typing import Iterable

LOW_INFO_PATTERNS = [
    r'^\s*[😂🤣😄😁😊🥺❤️♥️🤍🙏👍]+\s*$',
    r'^\s*(ok|okay|โอเค|โดย|ໂດຍ|ครับ|ค่ะ|จ้า|อือ|อืม|嗯|嗯嗯|哦|好|555+|อืมๆ)\s*$',
]
CARE_PATTERNS = [
    r'ไม่สบาย', r'ບໍສະບາຍ', r'เหนื่อย', r'ເມືອຍ', r'ป่วย', r'เจ็บ', r'ปวด',
    r'不舒服', r'难受', r'生病', r'累', r'头疼', r'发烧',
]
AFFECTION_PATTERNS = [
    r'แฟน', r'คิดถึง', r'รอ', r'โทรหา', r'ຄິດຮອດ', r'ໂທຫາ', r'ຮັກ', r'想你', r'等你'
]


def detect_language(text: str) -> str:
    if not text:
        return 'unknown'
    if re.search(r'[\u0E80-\u0EFF]', text):
        return 'Lao'
    if re.search(r'[\u0E00-\u0E7F]', text):
        return 'Thai'
    if re.search(r'[\u4E00-\u9FFF]', text):
        return 'Chinese'
    if re.search(r'[A-Za-z]', text):
        return 'English/Latin'
    return 'unknown'


def is_low_info(text: str) -> bool:
    s = (text or '').strip()
    return (not s) or any(re.search(p, s, re.I) for p in LOW_INFO_PATTERNS)


def approx_translate(text: str) -> str:
    rules = [
        (r'ไม่สบาย|ບໍສະບາຍ', '在说自己不舒服/身体状态不好'),
        (r'เหนื่อย|ເມືອຍ', '在说自己累了'),
        (r'กลับบ้าน|ກັບບ້ານ', '在说回家/已经回家/准备回家'),
        (r'เลิกงาน|ເລີກວຽກ', '在说下班了'),
        (r'คิดถึง|ຄິດຮອດ', '在表达想念/依恋'),
        (r'โทรหา|ໂທຫາ', '在说之后会打电话/联系'),
        (r'ขอบคุณ|ຂອບຄຸນ', '在表示感谢'),
        (r'โอเค|โดย|ໂດຍ', '语气性短回复，类似“好/嗯/哦”'),
    ]
    for pattern, meaning in rules:
        if re.search(pattern, text, re.I):
            return meaning
    return f'原文为{detect_language(text)}，需按上下文理解；整体是普通聊天内容。'


def summarize_mood(text: str) -> str:
    if re.search(r'ไม่สบาย|ບໍສະບາຍ|难受|不舒服|累|ເມືອຍ|เหนื่อย', text, re.I):
        return '用户状态偏脆弱/需要安抚，建议优先关怀。'
    if re.search(r'แฟน|คิดถึง|ຄິດຮອດ|รัก|想你|等你|โทรหา|ໂທຫາ', text, re.I):
        return '语气偏亲密暧昧，适合轻柔陪伴式回复。'
    if re.search(r'กลับบ้าน|ກັບບ້ານ|ไป|ຈະໄປ|明天', text, re.I):
        return '主要是在报备行程/动态，适合短回复加一句关心。'
    if re.search(r'โดย|ໂດຍ|โอเค|😂|😊|🥺', text, re.I):
        return '这是低信息量维持聊天节奏的消息，回复宜短。'
    return '普通闲聊，保持自然简短即可。'


def detect_preferred_language(memory_md: str, target_name: str) -> str:
    if 'Preferred language: Lao' in memory_md or 'ເກຍ' in target_name:
        return 'Lao'
    if 'Preferred language: Thai' in memory_md:
        return 'Thai'
    return 'user language'


def recent_languages(texts: Iterable[str]) -> list[str]:
    return [detect_language(t) for t in texts if (t or '').strip()]
