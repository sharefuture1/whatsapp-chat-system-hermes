from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from .language import collapse_whitespace


@dataclass(slots=True)
class TranslationEntry:
    source: str  # 原始文本（老挝语/泰语）
    translation: str  # 正确的中文翻译
    source_lang: str  # 'Lao' | 'Thai'
    count: int = 1  # 出现次数
    last_seen: float = 0.0  # Unix timestamp
    corrected: bool = False  # True=用户确认过，False=初译/待确认

    def touch(self, now: float) -> None:
        self.count += 1
        self.last_seen = now


class TranslationMemory:
    """
    翻译记忆库：持久化 JSON，按 source text 索引。
    每次翻译前查库，未命中则 AI 翻译并写入，初译标记 corrected=False 供人工审核。
    """

    _lock = threading.Lock()

    def __init__(self, memory_dir: Path) -> None:
        self._path = Path(memory_dir) / "translation_memory.json"
        self._entries: dict[str, TranslationEntry] = {}
        self._load()

    # ------------------------------------------------------------------ public API

    def get(self, source: str, source_lang: str) -> str | None:
        """查库，返回翻译或 None（未命中）。"""
        key = self._key(source)
        entry = self._entries.get(key)
        if entry is None:
            return None
        # 语言也要匹配（老挝语和泰语有些词形相近但意思不同）
        if entry.source_lang != source_lang:
            return None
        return entry.translation

    def put(
        self,
        source: str,
        translation: str,
        source_lang: str,
        *,
        corrected: bool = False,
        now: float = 0.0,
    ) -> None:
        """写入/更新一条翻译记录。"""
        key = self._key(source)
        entry = self._entries.get(key)
        now = now or 0.0
        if entry is not None:
            entry.translation = translation
            entry.source_lang = source_lang
            entry.corrected = entry.corrected or corrected
            entry.touch(now)
        else:
            self._entries[key] = TranslationEntry(
                source=source,
                translation=translation,
                source_lang=source_lang,
                count=1,
                last_seen=now,
                corrected=corrected,
            )
        self._save()

    def review_update(self, source: str, translation: str, source_lang: str) -> bool:
        """
        人工纠正：更新翻译并标记为 confirmed。
        返回 True 表示更新成功，False 表示找不到对应记录。
        """
        key = self._key(source)
        entry = self._entries.get(key)
        if entry is None:
            return False
        entry.translation = translation
        entry.source_lang = source_lang
        entry.corrected = True
        self._save()
        return True

    def unreviewed(self) -> Iterable[TranslationEntry]:
        """返回所有待审核（corrected=False）的记录，按 last_seen 降序。"""
        return sorted(
            (e for e in self._entries.values() if not e.corrected),
            key=lambda e: e.last_seen,
            reverse=True,
        )

    def all(self) -> Iterable[TranslationEntry]:
        return self._entries.values()

    def stats(self) -> dict:
        total = len(self._entries)
        reviewed = sum(1 for e in self._entries.values() if e.corrected)
        return {"total": total, "reviewed": reviewed, "pending": total - reviewed}

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _key(source: str) -> str:
        """归一化键：小写+去空白"""
        return collapse_whitespace(source.lower())

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for key, val in raw.items():
                try:
                    self._entries[key] = TranslationEntry(**val)
                except Exception:
                    pass  # 跳过格式损坏的旧记录
        except Exception:
            pass  # fail-soft：文件损坏则从空库开始

    def _save(self) -> None:
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                data = {k: asdict(v) for k, v in self._entries.items()}
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass  # fail-soft：写入失败不影响主流程
