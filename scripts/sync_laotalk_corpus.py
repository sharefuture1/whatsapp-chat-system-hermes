#!/usr/bin/env python3
"""
sync_laotalk_corpus.py — 从 LaoTalk 拉取最新 phrase_dict.json 到本地

用法:
    python sync_laotalk_corpus.py              # 直接拉取
    python sync_laotalk_corpus.py --dry-run   # 不写入，只看会改什么

定时: 每小时 (cron: 0 * * * *)
环境变量:
    LT_CORPUS_URL  LaoTalk corpus/dict 接口地址
                   默认: http://localhost:3020/api/corpus/dict
    LT_CORPUS_DEST 写入目标路径
                   默认: /var/www/laotalk-beta/backend/shared_corpus/phrase_dict.json
    LT_CORPUS_SECRET  如果 LaoTalk 端设置了 X-Corpus-Secret
"""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import urllib.request
import pathlib

DEFAULT_URL = "http://localhost:3020/api/corpus/dict"
DEFAULT_DEST = "/var/www/laotalk-beta/backend/shared_corpus/phrase_dict.json"


def fetch_dict(url: str, secret: str) -> dict[str, str] | None:
    headers = {"Accept": "application/json"}
    if secret:
        headers["X-Corpus-Secret"] = secret
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.load(resp)
                return data.get("dict", {})
    except Exception as exc:
        print(f"[sync] 获取词典失败: {exc}", file=sys.stderr)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="从 LaoTalk 拉取共享短语词典")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = os.environ.get("LT_CORPUS_URL", DEFAULT_URL).strip()
    dest = os.environ.get("LT_CORPUS_DEST", DEFAULT_DEST).strip()
    secret = os.environ.get("LT_CORPUS_SECRET", "").strip()

    print(f"[sync] 从 {url} 拉取词典 → {dest}")
    new_dict = fetch_dict(url, secret)
    if new_dict is None:
        print("[sync] 拉取失败，跳过")
        sys.exit(1)

    # 读取本地已有词典，比对 hash
    old_dict: dict[str, str] = {}
    old_hash = ""
    if pathlib.Path(dest).exists():
        try:
            with open(dest, encoding="utf-8") as f:
                old_dict = json.load(f)
            old_hash = hashlib.md5(
                json.dumps(old_dict, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:12]
        except Exception:
            pass

    new_hash = hashlib.md5(
        json.dumps(new_dict, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]
    print(f"[sync] 旧词典: {len(old_dict)} 条 (hash={old_hash})")
    print(f"[sync] 新词典: {len(new_dict)} 条 (hash={new_hash})")

    if old_hash == new_hash:
        print("[sync] 词典无变化，跳过写入")
        return

    added = len(new_dict) - len(old_dict)
    print(f"[sync] 变化: {'+' if added >= 0 else ''}{added} 条")

    if args.dry_run:
        print("[sync] [dry-run] 不会写入文件")
        return

    # 写入目标
    dest_path = pathlib.Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(new_dict, f, ensure_ascii=False, indent=2)
    tmp.rename(dest_path)
    print(f"[sync] 已写入 {dest_path} (hash={new_hash})")


if __name__ == "__main__":
    main()
