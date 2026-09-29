"""Measure bounded fixture capture/parse memory without persisting data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tracemalloc
from typing import Sequence

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.ingestion.registry import adapter_spec, create_adapter


def profile(university: str, fixture_dir: Path | None) -> dict[str, int | str]:
    spec = adapter_spec(university)
    selected_fixture = fixture_dir or spec.default_fixture_dir
    adapter = create_adapter(spec.slug)
    tracemalloc.start()
    try:
        captured = adapter.capture(mode="fixture", fixture_dir=selected_fixture)
        raw, canonical = adapter.parse(captured)
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        close = getattr(adapter, "close", None)
        if close is not None:
            close()
        tracemalloc.stop()
    return {
        "university": spec.slug,
        "snapshot_count": len(raw.snapshots),
        "source_bytes": sum(len(snapshot.body) for snapshot in raw.snapshots),
        "program_count": len(canonical.programs),
        "curriculum_item_count": sum(len(curriculum.items) for curriculum in canonical.curricula),
        "current_traced_bytes": current_bytes,
        "peak_traced_bytes": peak_bytes,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile fixture ingestion memory")
    parser.add_argument("--university", choices=("bmstu", "hse"), default="bmstu")
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = json.dumps(profile(args.university, args.fixture_dir), ensure_ascii=False, indent=2) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(args.out)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
