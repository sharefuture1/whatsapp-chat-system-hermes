"""FR-AI-014: identity of the exact stored source version; no trimming."""

from __future__ import annotations

import hashlib


def source_text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
