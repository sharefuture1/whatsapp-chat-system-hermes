"""Structured profile sidecar.

Writes a JSON sidecar alongside the markdown memory file so the
HTTP layer can read priority / preferred language without
matching on freeform markdown substrings.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .profile import UserProfile


@dataclass(slots=True)
class StructuredProfile:
    preferred_language: str
    tone: str
    warmth: str
    engagement_stage: str
    priority: str
    sensitivities: list[str]
    topics: list[str]
    response_style: list[str]
    follow_up_suggestions: list[str]
    donts: list[str]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_user_profile(cls, profile: UserProfile) -> "StructuredProfile":
        priority = "high" if any("comfort" in s.lower() or "vulnerable" in s.lower() for s in profile.sensitivities) else "normal"
        return cls(
            preferred_language=profile.preferred_language,
            tone=profile.tone,
            warmth=profile.warmth,
            engagement_stage=profile.engagement_stage,
            priority=priority,
            sensitivities=profile.sensitivities,
            topics=profile.topics,
            response_style=profile.response_style,
            follow_up_suggestions=profile.follow_up_suggestions,
            donts=profile.donts,
        )


def sidecar_path(memory_md_path: Path) -> Path:
    return memory_md_path.with_suffix(".json")


def write_sidecar(memory_md_path: Path, profile: UserProfile) -> Path:
    path = sidecar_path(memory_md_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = StructuredProfile.from_user_profile(profile).to_json()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def read_sidecar(user_id: str, memory_dir: Path) -> dict[str, Any] | None:
    for path in memory_dir.glob(f"*__{user_id}.json"):
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    return None
