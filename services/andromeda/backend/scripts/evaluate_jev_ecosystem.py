"""Run the offline Jev ecosystem comparison harness."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from andromeda.infrastructure.jev.question_registry import QuestionRegistry  # type: ignore[import-untyped]
from evals.jev.harness import build_offline_report, git_head

logger = logging.getLogger("andromeda.scripts.evaluate_jev_ecosystem")
REGISTRY_PATH = ROOT / "config" / "jev" / "question-definitions.v1.yaml"
CASES_PATH = ROOT / "evals" / "jev" / "corpus" / "decision-cases.v1.jsonl"
MANIFEST_PATH = ROOT / "config" / "jev" / "locks" / "decisions.v1.lock.json.meta.json"
TOOLS_PATH = ROOT / "evals" / "jev" / "TOOLS.lock"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run safe offline Jev ecosystem evaluation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    registry = QuestionRegistry.from_file(REGISTRY_PATH)
    cases = tuple(_jsonl(CASES_PATH))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tools = json.loads(TOOLS_PATH.read_text(encoding="utf-8"))
    report = build_offline_report(
        registry=registry,
        cases=cases,
        lock_manifest=manifest,
        tools_manifest=tools,
        git_commit=git_head(ROOT),
    )
    if args.check:
        _validate(report.as_dict(), registry_hash=manifest.get("registry_hash"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("jev_ecosystem_report_written cases=%d calibration_status=%s", len(cases), report.calibration_status)
    return 0


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _validate(report: dict[str, object], *, registry_hash: object) -> None:
    if report.get("schema_version") != "andromeda-jev-ecosystem-report.v1":
        raise ValueError("unknown Jev ecosystem report schema")
    if report.get("registry_hash") != registry_hash:
        raise ValueError("report registry hash does not match calibration manifest")
    if report.get("calibration_status") not in {"fixture_only", "shadow_only", "production_ready"}:
        raise ValueError("report calibration status is invalid")


if __name__ == "__main__":
    raise SystemExit(main())
