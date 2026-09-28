"""Fail on broken local Markdown links in current repository documentation."""

from __future__ import annotations

import re
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
EXCLUDED_PARTS = {".git", ".agents", ".codex", ".venv", "node_modules", ".next", "test-results", "coverage"}


def markdown_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.md")
        if not EXCLUDED_PARTS.intersection(path.parts)
        and "fixtures" not in path.parts
    ]


def main() -> int:
    failures: list[str] = []
    for document in markdown_files():
        for raw_target in LINK_PATTERN.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip().split("#", 1)[0]
            if "::" in target:
                target = target.split("::", 1)[0]
            if target.startswith("<") or not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = (document.parent / target).resolve()
            try:
                target_path.relative_to(ROOT)
            except ValueError:
                failures.append(f"{document.relative_to(ROOT)}: link escapes repository: {raw_target}")
                continue
            if not target_path.exists():
                failures.append(f"{document.relative_to(ROOT)}: missing link target: {raw_target}")
    if failures:
        print("Documentation link audit failed:")
        print("\n".join(failures))
        return 1
    print(f"Documentation link audit passed ({len(markdown_files())} Markdown files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
