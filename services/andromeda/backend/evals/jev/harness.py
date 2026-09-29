"""Offline, source-safe comparison harness for the Jev ecosystem paths.

The harness deliberately reports unavailable paths as unavailable.  It does
not turn a fixture corpus into production accuracy and never stores provider
prompts or responses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from andromeda.modules.conversation.services.decision_model import RuleBasedDecisionModel  # type: ignore[import-untyped]
from andromeda.infrastructure.jev.question_registry import QuestionRegistry  # type: ignore[import-untyped]


@dataclass(frozen=True)
class PathOutcome:
    status: str
    evaluated_cases: int
    unavailable_cases: int
    fallback_cases: int


@dataclass(frozen=True)
class EcosystemEvaluationReport:
    schema_version: str
    registry_hash: str
    dataset_hash: str
    git_commit: str
    calibration_status: str
    calibration_artifact_id: str
    paths: dict[str, PathOutcome]

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["paths"] = {key: asdict(item) for key, item in self.paths.items()}
        return value


def build_offline_report(
    *,
    registry: QuestionRegistry,
    cases: tuple[dict[str, Any], ...],
    lock_manifest: dict[str, Any],
    tools_manifest: dict[str, Any],
    git_commit: str,
) -> EcosystemEvaluationReport:
    model = RuleBasedDecisionModel()
    deterministic_count = 0
    fallback_count = 0
    unavailable_count = 0
    for case in cases:
        definition_id = case.get("definition_id")
        input_data = case.get("input")
        if definition_id == "intent.v1" and isinstance(input_data, dict) and isinstance(input_data.get("text"), str):
            model.resolve_intent(input_data["text"])
            deterministic_count += 1
        elif definition_id == "metric.v1" and isinstance(input_data, dict) and isinstance(input_data.get("text"), str):
            candidates = tuple(item for item in input_data.get("candidates", ()) if isinstance(item, str))
            model.resolve_metric(input_data["text"], candidates=candidates)
            deterministic_count += 1
        else:
            unavailable_count += 1

    manifest_status = str(lock_manifest.get("status", "unknown"))
    artifact_id = str(lock_manifest.get("artifact_id", "unknown"))
    del tools_manifest
    return EcosystemEvaluationReport(
        schema_version="andromeda-jev-ecosystem-report.v1",
        registry_hash=registry.content_hash(),
        dataset_hash=lock_manifest.get("dataset_hash", "unknown"),
        git_commit=git_commit,
        calibration_status=manifest_status,
        calibration_artifact_id=artifact_id,
        paths={
            "deterministic": PathOutcome("available", deterministic_count, unavailable_count, fallback_count),
            "official_jev": PathOutcome("not_run_offline", 0, len(cases), 0),
            "system_one": PathOutcome("eval_only_not_run", 0, len(cases), 0),
            "jevql": PathOutcome("optional_not_run", 0, len(cases), 0),
        },
    )


def content_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(root: Path) -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


__all__ = ["EcosystemEvaluationReport", "PathOutcome", "build_offline_report", "content_hash", "git_head"]
