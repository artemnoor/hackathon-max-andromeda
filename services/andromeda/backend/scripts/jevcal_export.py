"""Export Andromeda evaluation data to the exact upstream jevcal input format."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from evals.jev.exporters import EvaluationExportError, JevcalExportBundle, build_jevcal_bundle


logger = logging.getLogger("andromeda.scripts.jevcal_export")
REGISTRY_PATH = ROOT / "config" / "jev" / "question-definitions.v1.yaml"
CORPUS_PATH = ROOT / "evals" / "jev" / "corpus" / "decision-cases.v1.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="native jevcal JSONL output path")
    parser.add_argument("--questions-output", type=Path, help="native jevcal questions YAML path")
    parser.add_argument("--source", choices=("fixture", "production"), default="fixture")
    parser.add_argument("--check", action="store_true", help="validate generated native files with upstream jevcal")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    if args.source == "production":
        raise SystemExit("production corpus must be supplied explicitly; committed fixture is not production data")

    registry = QuestionRegistry.from_file(REGISTRY_PATH)
    source_rows = _read_source_rows(CORPUS_PATH)
    bundle = build_jevcal_bundle(registry, source_rows)
    output = args.output
    questions_output = args.questions_output or output.with_name("questions.yaml")
    output.parent.mkdir(parents=True, exist_ok=True)
    questions_output.parent.mkdir(parents=True, exist_ok=True)
    serialized = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in bundle.rows
    )
    output.write_text(serialized, encoding="utf-8")
    questions_output.write_text(
        yaml.safe_dump(
            {"model": "jev-latest", "questions": bundle.questions},
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )
    splits = {
        str(meta["split"])
        for row in bundle.rows
        if isinstance((meta := row.get("andromeda")), dict) and "split" in meta
    }
    metadata = {
        "schema_version": "jevcal-export.v2",
        "source_kind": args.source,
        "registry_hash": bundle.registry_hash,
        "questions_path": str(questions_output),
        "dataset_hash": "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "case_count": len(bundle.rows),
        "definitions": sorted(bundle.questions),
        "splits": sorted(splits),
        "calibration": {
            "thresholds": "upstream_jevcal",
            "metrics": "upstream_jevcal",
        },
    }
    output.with_suffix(output.suffix + ".meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    logger.info(
        "jevcal_export_completed source_kind=%s cases=%s definitions=%s registry_hash=%s",
        args.source,
        len(bundle.rows),
        len(bundle.questions),
        bundle.registry_hash,
    )
    if args.check:
        _lint_with_upstream(questions_output, output)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


def _read_source_rows(path: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationExportError(f"invalid JSON corpus row {line_number}") from exc
        if not isinstance(row, dict):
            raise EvaluationExportError(f"corpus row {line_number} must be an object")
        rows.append(row)
    if not rows:
        raise EvaluationExportError(f"corpus is empty: {path}")
    return tuple(rows)


def _lint_with_upstream(questions_path: Path, rows_path: Path) -> None:
    try:
        from jevcal.spec import load_questions, load_rows  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - optional extra guard
        raise RuntimeError("install the evaluation extra to validate jevcal exports") from exc
    questions = load_questions(questions_path)
    rows = load_rows(rows_path)
    if set(questions.questions) != {
        "intent.v1",
        "metric.v1",
        "next-action.v1",
        "presentation.v1",
        "semantic-feature.v1",
    }:
        raise EvaluationExportError("upstream jevcal questions do not match registry definitions")
    if len(rows) == 0:
        raise EvaluationExportError("upstream jevcal accepted an empty dataset")
    logger.info("jevcal_upstream_lint_passed questions=%s rows=%s", len(questions.questions), len(rows))


if __name__ == "__main__":
    raise SystemExit(main())
