#!/usr/bin/env python3
"""Fail if project code or submission materials contain Chinese characters."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = [
    "app",
    "scripts",
    "docs",
    "README.md",
    ".env.example",
    "requirements.txt",
    "systemd",
]
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".html",
    ".txt",
    ".service",
    ".example",
    ".env",
    ".json",
}
SKIP_PARTS = {"__pycache__", ".git", ".venv"}
HAN_RE = re.compile(r"[\u4e00-\u9fff]")


def iter_files(paths: list[str]):
    for raw in paths:
        path = ROOT / raw
        if not path.exists():
            continue
        if path.is_file():
            yield path
            continue
        for item in path.rglob("*"):
            if any(part in SKIP_PARTS for part in item.parts):
                continue
            if item.is_file():
                yield item


def is_text_file(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES or path.name in {"README.md", "requirements.txt"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=DEFAULT_PATHS)
    args = parser.parse_args()

    failures: list[str] = []
    for path in iter_files(args.paths):
        if not is_text_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if HAN_RE.search(line):
                rel = path.relative_to(ROOT)
                failures.append(f"{rel}:{line_no}: {line.strip()}")

    if failures:
        print("Chinese characters found in English-only project material:")
        for item in failures:
            print(item)
        return 1

    print("English content check passed: no Chinese characters found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
