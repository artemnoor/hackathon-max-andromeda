"""Print a deterministic BMSTU admission-benefit coverage report."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from ingest_bmstu_admission_benefits import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report BMSTU admission-benefit source coverage")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--benefit-fixture-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(
        mode=args.mode,
        year=args.year,
        fixture_dir=args.fixture_dir,
        benefit_fixture_dir=args.benefit_fixture_dir,
        database_url=None,
        dry_run=True,
        allow_partial=True,
    )
    print(json.dumps({"report": asdict(report)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
