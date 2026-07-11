#!/usr/bin/env python3
"""
review_translations.py — 翻译复习工具

用法:
    python review_translations.py                        # 交互式复习
    python review_translations.py --list                # 只列出待纠正条目
    python review_translations.py --auto-approve       # 自动批准已有人工纠正
    python review_translations.py --export CSV         # 导出 CSV 报告

扫描 src/whatsapp_chat_system/memory/ 下所有用户的翻译记忆文件，
显示 corrected=False 的条目（未经人工确认），供人工审查和纠正。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MEMORY_DIR = Path(__file__).parent / "memory"

INDENT = "  "
BANNER = """
╔══════════════════════════════════════════════════════╗
║          翻译复习工具  Translation Review              ║
║  只显示 corrected=False 的条目（待人工确认）            ║
╚══════════════════════════════════════════════════════╝
"""


def load_memories() -> list[dict]:
    """Load all translation memory entries from all user files."""
    entries = []
    if not MEMORY_DIR.exists():
        return entries
    for user_file in sorted(MEMORY_DIR.glob("*/translations.json")):
        user_id = user_file.parent.name
        try:
            with open(user_file, encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items", {})
            for mid, item in items.items():
                entries.append(
                    {
                        "user_id": user_id,
                        "message_id": mid,
                        "source_lang": item.get("source_lang", "?"),
                        "source_text": item.get("source_text", ""),
                        "zh": item.get("zh", ""),
                        "corrected": item.get("corrected", False),
                        "created_at": item.get("created_at", 0),
                        "updated_at": item.get("updated_at", 0),
                    }
                )
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [WARN] {user_file.name}: {exc}", file=sys.stderr)
    return entries


def is_likely_correct(zh: str) -> bool:
    """Heuristic: Chinese text with no obviously wrong patterns."""
    if not zh:
        return False
    bad = {"原文为", "在表达", "在说", "需要", "请按", "整体是", "需按"}
    return not any(zh.startswith(b) for b in bad)


def format_age(ts: float) -> str:
    age_s = time.time() - ts
    if age_s < 60:
        return f"{age_s:.0f}s"
    if age_s < 3600:
        return f"{age_s / 60:.0f}m"
    if age_s < 86400:
        return f"{age_s / 3600:.0f}h"
    return f"{age_s / 86400:.0f}d"


def print_entry(i: int, e: dict, show_user: bool = True) -> None:
    ts = (
        datetime.fromtimestamp(e["updated_at"]).strftime("%m-%d %H:%M")
        if e["updated_at"]
        else "??-?? ??:??"
    )
    age = format_age(e["updated_at"]) if e["updated_at"] else "??"
    tag = "✅" if e["corrected"] else "❗"
    print(f"\n{INDENT}[{i}] {tag} {e['source_lang']} | {ts} ({age} ago)")
    if show_user:
        print(f"{INDENT}    user   : {e['user_id']}")
    print(f"{INDENT}    原文   : {e['source_text']}")
    print(f"{INDENT}    译文   : {e['zh']}")


def interactive_review(entries: list[dict]) -> dict[int, str]:
    """
    Interactively review entries.
    Returns: {entry_index: corrected_zh_value}
    """
    corrections: dict[int, str] = {}
    total = len(entries)

    print(BANNER)
    print(f"共 {total} 条待审查条目\n")

    for i, entry in enumerate(entries):
        print_entry(i, entry)
        while True:
            prompt = f"\n{INDENT}请输入纠正后的中文译文"
            if entry["corrected"]:
                prompt += " (回车保留当前译文)"
            prompt += " [n=下一个/q=退出]: "
            try:
                raw = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n已保存的纠正:", len(corrections))
                return corrections

            if raw in ("q", "quit", "exit"):
                print("\n已保存的纠正:", len(corrections))
                return corrections
            if raw in ("n", ""):
                break
            corrections[i] = raw
            print(f"{INDENT}  ✓ 已记录: {raw}")
            break

    print(f"\n审查完成，共纠正 {len(corrections)} 条")
    return corrections


def apply_corrections(entries: list[dict], corrections: dict[int, str]) -> int:
    """Write corrections back to disk files. Returns number of files updated."""
    # Group by user
    by_user: dict[str, list[tuple[int, dict, str]]] = defaultdict(list)
    for idx, new_zh in corrections.items():
        e = entries[idx]
        by_user[e["user_id"]].append((idx, e, new_zh))

    files_updated = 0
    for user_id, items in by_user.items():
        mem_dir = MEMORY_DIR / user_id
        if not mem_dir.exists():
            continue
        json_file = mem_dir / "translations.json"
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {"version": 1, "items": {}}

        changed = False
        for _, e, new_zh in items:
            mid = e["message_id"]
            if mid in data["items"]:
                data["items"][mid]["zh"] = new_zh
                data["items"][mid]["corrected"] = True
                data["items"][mid]["updated_at"] = time.time()
                changed = True

        if changed:
            bak = mem_dir / f"translations.json.bak.{int(time.time())}"
            with open(bak, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            files_updated += 1
            print(f"  ✓ {user_id}: 更新 {len(items)} 条 → {json_file}")

    return files_updated


def export_csv(entries: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            [
                "user_id",
                "message_id",
                "source_lang",
                "source_text",
                "zh",
                "corrected",
                "created_at",
                "updated_at",
            ],
        )
        w.writeheader()
        for e in entries:
            row = dict(e)
            row["created_at"] = (
                datetime.fromtimestamp(e["created_at"]).isoformat()
                if e["created_at"]
                else ""
            )
            row["updated_at"] = (
                datetime.fromtimestamp(e["updated_at"]).isoformat()
                if e["updated_at"]
                else ""
            )
            w.writerow(row)
    print(f"导出 {len(entries)} 条 → {path}")


def stats_summary(entries: list[dict]) -> None:
    total = len(entries)
    corrected = sum(1 for e in entries if e["corrected"])
    by_lang = defaultdict(list)
    for e in entries:
        by_lang[e["source_lang"]].append(e)

    print(BANNER)
    print(f"  总条目   : {total}")
    print(
        f"  已确认   : {corrected} ({100 * corrected / total:.0f}%)"
        if total
        else "  已确认   : 0"
    )
    print(f"  待审查   : {total - corrected}")

    print("\n  按语言:")
    for lang, lang_entries in sorted(by_lang.items(), key=lambda x: -len(x[1])):
        c = sum(1 for e in lang_entries if e["corrected"])
        t = len(lang_entries)
        print(f"    {lang:8s}: {t} 条 (已确认 {c})")

    likely_wrong = [
        e for e in entries if not e["corrected"] and not is_likely_correct(e["zh"])
    ]
    print(f"\n  可能错误的: {len(likely_wrong)} 条")
    if likely_wrong:
        for i, e in enumerate(likely_wrong[:5]):
            print_entry(i, e)
        if len(likely_wrong) > 5:
            print(f"  ... 还有 {len(likely_wrong) - 5} 条")


def main() -> None:
    parser = argparse.ArgumentParser(description="翻译复习工具")
    parser.add_argument("--list", "-l", action="store_true", help="只列出待审查条目")
    parser.add_argument(
        "--auto-approve",
        "-a",
        action="store_true",
        help="自动批准已有 corrected=True 的条目（只列出待审查）",
    )
    parser.add_argument("--export", "-e", metavar="CSV_FILE", help="导出 CSV 报告")
    parser.add_argument(
        "--since",
        type=float,
        metavar="DAYS",
        help="只显示最近 N 天内的条目（默认全部）",
    )
    args = parser.parse_args()

    entries = load_memories()
    if not entries:
        print("没有找到翻译记忆文件（memory 目录为空）", file=sys.stderr)
        sys.exit(0)

    # Filter: only uncorrected unless --auto-approve
    if args.auto_approve:
        display_entries = [e for e in entries if e["corrected"]]
    else:
        display_entries = [e for e in entries if not e["corrected"]]

    # Time filter
    if args.since:
        cutoff = time.time() - args.since * 86400
        display_entries = [
            e for e in display_entries if e.get("updated_at", 0) >= cutoff
        ]

    stats_summary(entries)

    if args.list or args.export:
        print(f"\n{'─' * 60}")
        for i, e in enumerate(display_entries):
            print_entry(i, e)
        if args.export:
            export_csv(display_entries, Path(args.export))
        return

    if not display_entries:
        print("\n没有需要审查的条目 ✓")
        if args.auto_approve:
            print("所有条目都已有人工确认。")
        return

    corrections = interactive_review(display_entries)
    if corrections:
        orig_idx_map = {id(e): i for i, e in enumerate(entries)}
        real_corrections = {
            orig_idx_map[id(display_entries[idx])]: new_zh
            for idx, new_zh in corrections.items()
            if id(display_entries[idx]) in orig_idx_map
        }
        updated = apply_corrections(entries, real_corrections)
        print(f"\n已更新 {updated} 个用户文件。")


if __name__ == "__main__":
    main()
