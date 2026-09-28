"""Validate Jev evaluation artifacts and scan them for accidental secrets."""

from __future__ import annotations

import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from andromeda.infrastructure.jev.question_registry import QuestionRegistry


SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|authorization|cookie|password|secret|access[_-]?token)\s*[:=]"),
    re.compile(r"(?i)bearer\s+[a-z0-9._-]{16,}"),
    re.compile(r"\bsk-[a-z0-9_-]{16,}\b", re.IGNORECASE),
)


def main() -> int:
    eval_root = ROOT / "evals" / "jev"
    cases_path = eval_root / "corpus" / "decision-cases.v1.jsonl"
    labels_path = eval_root / "labels" / "decision-labels.v1.jsonl"
    schema_path = eval_root / "schemas" / "decision-case.schema.json"
    registry = QuestionRegistry.from_file(ROOT / "config" / "jev" / "question-definitions.v1.yaml")
    cases = _read_jsonl(cases_path)
    labels = _read_jsonl(labels_path)

    _validate_schema(cases, json.loads(schema_path.read_text(encoding="utf-8")))
    _assert_unique(cases, "case_id")
    _assert_unique(labels, "case_id")
    if {row["case_id"] for row in cases} != {row["case_id"] for row in labels}:
        raise ValueError("corpus and label case IDs differ")

    definition_ids = {definition.definition_id for definition in registry.all()}
    splits: dict[str, set[str]] = {definition_id: set() for definition_id in definition_ids}
    for row in cases:
        if row["definition_id"] not in definition_ids:
            raise ValueError(f"unknown definition id: {row['definition_id']}")
        definition = registry.get(row["definition_id"])
        if row["definition_version"] != definition.version:
            raise ValueError(f"definition version mismatch: {row['case_id']}")
        splits[row["definition_id"]].add(row["split"])
        _scan_for_secrets(row)
    for definition_id, present in splits.items():
        if present != {"train", "dev", "heldout"}:
            raise ValueError(f"incomplete evaluation splits for {definition_id}: {sorted(present)}")

    print(json.dumps({"valid": True, "cases": len(cases), "definitions": len(definition_ids)}, indent=2))
    return 0


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: row must be an object")
        rows.append(value)
    return rows


def _validate_schema(rows: list[dict[str, object]], schema: dict[str, object]) -> None:
    try:
        from jsonschema import validate
    except ImportError:  # pragma: no cover - dev extra is present in CI
        required = set(schema.get("required", ()))
        for row in rows:
            if not required.issubset(row):
                raise ValueError(f"schema required fields missing: {sorted(required - row.keys())}")
        return
    for row in rows:
        validate(row, schema)


def _assert_unique(rows: list[dict[str, object]], field: str) -> None:
    values = [row.get(field) for row in rows]
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {field}")


def _scan_for_secrets(value: object) -> None:
    serialized = json.dumps(value, ensure_ascii=False)
    if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
        raise ValueError("evaluation artifact contains a secret-like field")


if __name__ == "__main__":
    raise SystemExit(main())
