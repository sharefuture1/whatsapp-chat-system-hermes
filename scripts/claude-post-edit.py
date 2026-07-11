#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> int:
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def extract_path(payload: dict) -> str:
    tool_input = payload.get("tool_input") or {}
    return str(tool_input.get("file_path") or tool_input.get("path") or "")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0

    raw_path = extract_path(payload)
    if not raw_path:
        return 0

    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT / path
    try:
        path = path.resolve()
        path.relative_to(ROOT)
    except (OSError, ValueError):
        return 0
    if not path.is_file():
        return 0

    relative = path.relative_to(ROOT).as_posix()
    suffix = path.suffix.lower()

    if suffix == ".py":
        ruff = ROOT / ".venv/bin/ruff"
        if not ruff.exists():
            return 0
        if run([str(ruff), "format", relative]) != 0:
            return 2
        return run([str(ruff), "check", "--fix", relative])

    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        if suffix == ".jsx":
            # Node cannot parse JSX directly; Vite remains the authoritative slow build gate.
            return 0
        return run(["node", "--check", relative])

    if suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"invalid JSON in {relative}: {exc}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
