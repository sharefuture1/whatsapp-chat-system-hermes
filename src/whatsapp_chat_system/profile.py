from __future__ import annotations

import collections
import datetime as dt
import re
from dataclasses import dataclass

from .language import AFFECTION_PATTERNS, CARE_PATTERNS, detect_language, is_low_info


@dataclass(slots=True)
class UserProfile:
    preferred_language: str
    tone: str
    topics: list[str]
    sensitivities: list[str]
    warmth: str
    engagement_stage: str
    response_style: list[str]
    follow_up_suggestions: list[str]
    donts: list[str]


def detect_tone(texts: list[str]) -> str:
    blob = '\n'.join(texts)
    if not blob.strip():
        return 'unknown'
    if any(re.search(p, blob, re.I) for p in CARE_PATTERNS):
        return 'emotionally open / seeking comfort'
    if any(re.search(p, blob, re.I) for p in AFFECTION_PATTERNS):
        return 'warm / affectionate'
    if re.search(r'[😂🤣😄😁😊😍❤️🤍👍🙏🥺]', blob):
        return 'light / positive'
    if '?' in blob or '？' in blob:
        return 'inquisitive'
    if re.search(r'不|没|不要|不想|不去|拒绝|why|为什么', blob, re.I):
        return 'direct / problem-focused'
    return 'neutral'


def extract_topics(texts: list[str]) -> list[str]:
    joined = '\n'.join(texts)
    rules = [
        ('translation / language help', r'翻译|语言|老挝语|泰语|中文|english|lao|thai|什么意思|为什么'),
        ('travel / going somewhere', r'กลับบ้าน|ກັບບ້ານ|ไป|ຈະໄປ|万象|vientiane|หลวงพระบาง|ຫຼວງພະບາງ'),
        ('scheduling / tomorrow', r'明天|พรุ่งนี้|ມືອື່ນ|tomorrow'),
        ('relationship / affectionate chat', r'แฟน|คิดถึง|รอ|โทรหา|ຄິດຮອດ|ໂທຫາ|รัก|想你|等你'),
        ('health / discomfort', r'ไม่สบาย|ບໍສະບາຍ|เหนื่อย|ເມືອຍ|ป่วย|เจ็บ|难受|不舒服|累'),
        ('work / daily updates', r'ทำงาน|เลิกงาน|ວຽກ|ເລີກວຽກ|上班|下班'),
        ('greeting / small talk', r'hello|hi|你好|😂|哈哈|笑|โดย|ໂດຍ'),
        ('product / app learning', r'软件|app|学习'),
        ('business / service inquiry', r'价格|费用|多少|多少钱|服务|怎么卖|price|cost|service'),
    ]
    found = [name for name, pat in rules if re.search(pat, joined, re.I)]
    return found[:8] or ['general chat']


def detect_response_style(preferred_language: str, tone: str, user_texts: list[str]) -> list[str]:
    notes = []
    blob = '\n'.join(user_texts)
    if preferred_language in {'Thai', 'Lao'}:
        notes.append('Reply in the user language first and keep the phrasing local/natural.')
    if tone in {'warm / affectionate', 'emotionally open / seeking comfort'}:
        notes.append('Short, warm, companion-like replies work better than explanatory replies.')
    if re.search(r'โดย|ໂດຍ|โอเค|🥺|😊|😂', blob, re.I):
        notes.append('Handle low-information pings with ultra-short acknowledgements instead of long replies.')
    if any(re.search(p, blob, re.I) for p in CARE_PATTERNS):
        notes.append('Prioritize comfort and immediate reassurance when the user sounds tired or unwell.')
    if any(re.search(p, blob, re.I) for p in AFFECTION_PATTERNS):
        notes.append('Affectionate but light replies fit; avoid overcommitting to real-world promises.')
    if preferred_language == 'Chinese':
        notes.append('Chinese replies are acceptable; keep them direct and natural.')
    return notes or ['Keep replies concise, warm, and context-aware.']


def detect_engagement_stage(user_texts: list[str]) -> str:
    blob = '\n'.join(user_texts)
    if any(re.search(p, blob, re.I) for p in AFFECTION_PATTERNS):
        return 'warm ongoing companion-style chat'
    if any(re.search(p, blob, re.I) for p in CARE_PATTERNS):
        return 'emotionally vulnerable / seeking comfort'
    if re.search(r'学习|翻译|什么意思|为什么|怎么', blob, re.I):
        return 'exploring / learning / asking for understanding'
    if re.search(r'hello|hi|你好|😂', blob, re.I):
        return 'casual / warming up'
    return 'ongoing general conversation'


def infer_follow_up_suggestions(user_texts: list[str], topics: list[str], tone: str) -> list[str]:
    suggestions = []
    if 'health / discomfort' in topics:
        suggestions.append('When the user says they feel unwell or tired, reply immediately with comfort-first language and gentle care suggestions.')
    if 'relationship / affectionate chat' in topics:
        suggestions.append('Use short affectionate follow-ups such as asking whether they arrived, rested, or feel better now.')
    if 'travel / going somewhere' in topics:
        suggestions.append('Ask one simple follow-up about arrival, timing, or safety rather than a long reply.')
    if 'work / daily updates' in topics:
        suggestions.append('Acknowledge work/update messages quickly and pivot to rest, food, or how they feel.')
    if tone in {'warm / affectionate', 'emotionally open / seeking comfort'}:
        suggestions.append('Favor one-to-three-sentence replies with a soft emotional landing.')
    if any(is_low_info(t) for t in user_texts[-5:]):
        suggestions.append('If the user sends repeated short pings, batch them mentally and answer with one natural summary reply.')
    return suggestions[:6] or ['Continue with concise, pleasant, context-aware replies.']


def infer_donts(user_texts: list[str]) -> list[str]:
    blob = '\n'.join(user_texts)
    donts = [
        'Do not expose internal memory/tool/system errors to the user.',
        'Do not invent personal facts beyond what the conversation supports.',
        'Do not answer repeated low-information pings with long template-like messages.',
    ]
    if any(re.search(p, blob, re.I) for p in CARE_PATTERNS):
        donts.append('Do not ignore or delay replies when the user says they are unwell, tired, or emotionally vulnerable.')
    if any(re.search(p, blob, re.I) for p in AFFECTION_PATTERNS):
        donts.append('Do not make strong real-world promises or claims of physical presence.')
    return donts[:6]


def summarize_user_messages(texts: list[str]) -> UserProfile:
    langs = [detect_language(t) for t in texts if t.strip()]
    preferred = collections.Counter(langs).most_common(1)[0][0] if langs else 'unknown'
    tone = detect_tone(texts)
    topics = extract_topics(texts)
    sensitivities = []
    blob = '\n'.join(texts)
    if any(re.search(p, blob, re.I) for p in CARE_PATTERNS):
        sensitivities.append('Needs fast emotional acknowledgement when tired, unwell, or vulnerable')
    if any(re.search(p, blob, re.I) for p in AFFECTION_PATTERNS):
        sensitivities.append('Responds to affectionate, reassuring tone and continuity')
    if sum(1 for t in texts if is_low_info(t)) >= max(3, len(texts) // 4):
        sensitivities.append('Frequently sends short pings or filler words; conversation flow matters more than information density')
    if not sensitivities:
        sensitivities.append('No clear sensitivity yet')
    warmth = 'warm / affectionate' if any(re.search(p, blob, re.I) for p in AFFECTION_PATTERNS) or re.search(r'[❤️🤍🥺😊😍]', blob) else 'neutral-to-warm'
    return UserProfile(
        preferred_language=preferred,
        tone=tone,
        topics=topics,
        sensitivities=sensitivities[:4],
        warmth=warmth,
        engagement_stage=detect_engagement_stage(texts),
        response_style=detect_response_style(preferred, tone, texts),
        follow_up_suggestions=infer_follow_up_suggestions(texts, topics, tone),
        donts=infer_donts(texts),
    )


def render_md(user_name: str, user_id: str, role_label: str, first_seen: str, last_seen: str,
              session_ids: list[str], profile: UserProfile, recent_user_msgs: list[str],
              recent_assistant_msgs: list[str]) -> str:
    def bullets(items: list[str], fallback: str = '- none yet') -> str:
        return '\n'.join(f'- {x}' for x in items) if items else fallback

    return f'''# User Memory

- Name: {user_name}
- User ID: {user_id}
- Role: {role_label}
- Platform: whatsapp
- First seen: {first_seen}
- Last seen: {last_seen}
- Sessions: {', '.join(session_ids)}

## Soft Profile
- Preferred language: {profile.preferred_language}
- Tone: {profile.tone}
- Relationship warmth: {profile.warmth}
- Engagement stage: {profile.engagement_stage}

## Recurring topics
{bullets(profile.topics)}

## Sensitivities / conversation cautions
{bullets(profile.sensitivities)}

## Likely response preferences
{bullets(profile.response_style)}

## Potential interest / conversion clues
{bullets([x for x in profile.topics if x in {'product / app learning', 'business / service inquiry', 'translation / language help'}], '- no strong conversion clue yet')}

## Suggested next-step follow-ups
{bullets(profile.follow_up_suggestions)}

## Avoid / don'ts
{bullets(profile.donts)}

## Notes for happier chat
- Mirror the user's language unless there is a clear reason to switch.
- Prefer short, human-like replies over long formatted replies in casual chat.
- Use continuity: remember where they are, whether they are tired, going home, or feeling unwell.
- If multiple short messages arrive close together, answer naturally as one combined conversational turn.

## Recent user messages
{bullets(recent_user_msgs[-10:])}

## Recent assistant replies
{bullets(recent_assistant_msgs[-6:])}

## Last refreshed
- {dt.datetime.now(dt.UTC).isoformat()}
'''
