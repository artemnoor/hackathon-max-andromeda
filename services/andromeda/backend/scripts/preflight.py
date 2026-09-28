"""Validate parser/runtime capabilities without contacting external sources."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from andromeda.ingestion.capabilities import CapabilityPreflightError, preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Andromeda ingestion parser and system capabilities")
    parser.add_argument("--profile", action="append", choices=("bmstu", "hse"), default=[])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    profiles = tuple(args.profile) or ("bmstu", "hse")
    reports = []
    try:
        for profile in profiles:
            reports.append(preflight(profile).as_dict())
    except CapabilityPreflightError as exc:
        reports.append(exc.report.as_dict())
        print(json.dumps({"ready": False, "reports": reports}, ensure_ascii=False, indent=2))
        return 78
    print(json.dumps({"ready": True, "reports": reports}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
