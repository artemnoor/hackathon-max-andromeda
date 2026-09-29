"""Capture the official BMSTU tracer sources into the reproducible fixture."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.ingestion.universities.bmstu.capture import DEFAULT_FIXTURE_DIR, BmstuSource, write_fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    source = BmstuSource()
    try:
        captured = source.capture(mode="live")
        write_fixture(captured, args.out)
    finally:
        source.close()
    print(f"Captured {len(captured.snapshots)} official source snapshots into {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
