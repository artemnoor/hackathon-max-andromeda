from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from andromeda.infrastructure.jev.calibration import (
    CalibrationArtifactError,
    CascadeCalibrationAdapter,
)
from andromeda.infrastructure.jev.contracts import JevAnswerEvidence
from andromeda.infrastructure.jev.question_registry import QuestionRegistry

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = QuestionRegistry.from_file(ROOT / "config/jev/question-definitions.v1.yaml")
LOCK = ROOT / "config/jev/locks/decisions.v1.lock.json"
MANIFEST = ROOT / "config/jev/locks/decisions.v1.lock.json.meta.json"


def test_adapter_delegates_acceptance_to_upstream_cascade() -> None:
    adapter = CascadeCalibrationAdapter(
        lock_path=LOCK,
        manifest_path=MANIFEST,
        registry=REGISTRY,
        model="jev-latest",
    )
    result = adapter.evaluate(
        "intent.v1",
        JevAnswerEvidence(
            answer_kind="ChoiceAnswer",
            answer_value="catalog_search",
            confidence=0.99,
            probabilities={"catalog_search": 0.99, "unknown": 0.01},
            has_probability_evidence=True,
        ),
    )

    assert result.accepted is False
    assert result.reason == "calibration_rejected"
    assert result.threshold is None


def test_production_adapter_rejects_fixture_artifact() -> None:
    with pytest.raises(CalibrationArtifactError, match="not production-ready"):
        CascadeCalibrationAdapter(
            lock_path=LOCK,
            manifest_path=MANIFEST,
            registry=REGISTRY,
            model="jev-latest",
            production=True,
        )


def test_production_adapter_rejects_insufficient_support(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    data = __import__("json").loads(MANIFEST.read_text(encoding="utf-8"))
    data["status"] = "production_ready"
    manifest.write_text(__import__("json").dumps(data), encoding="utf-8")
    with pytest.raises(CalibrationArtifactError, match="support is insufficient"):
        CascadeCalibrationAdapter(
            lock_path=LOCK,
            manifest_path=manifest,
            registry=REGISTRY,
            model="jev-latest",
            production=True,
        )


def test_adapter_rejects_stale_registry_hash(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    data["registry_hash"] = "sha256:" + "0" * 64
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CalibrationArtifactError, match="registry hash is stale"):
        CascadeCalibrationAdapter(
            lock_path=LOCK,
            manifest_path=manifest,
            registry=REGISTRY,
            model="jev-latest",
        )


def test_adapter_rejects_expired_artifact(tmp_path: Path) -> None:
    lock_data = json.loads(LOCK.read_text(encoding="utf-8"))
    lock_data["created"] = "2000-01-01T00:00:00+00:00"
    manifest_data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    canonical = json.dumps(
        lock_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    manifest_data["lock_hash"] = (
        "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )
    lock_path = tmp_path / "expired.lock.json"
    manifest_path = tmp_path / "expired.lock.json.meta.json"
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(CalibrationArtifactError, match="calibration artifact is stale"):
        CascadeCalibrationAdapter(
            lock_path=lock_path,
            manifest_path=manifest_path,
            registry=REGISTRY,
            model="jev-latest",
            max_age_seconds=60,
        )


def test_production_action_lock_is_scoped_and_model_version_bound(
    tmp_path: Path,
) -> None:
    lock_data = json.loads(LOCK.read_text(encoding="utf-8"))
    lock_data["questions"] = {
        "next-action.v1": lock_data["questions"]["next-action.v1"]
    }
    lock_data["model_requested"] = "typesafe/jev"
    lock_data["model_observed"] = ["jev-1.13.0"]
    lock_data["provider"] = "polza"
    lock_data["questions"]["next-action.v1"]["threshold"] = 0.5
    lock_data["questions"]["next-action.v1"]["status"] = "ok"
    manifest_data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_data.update(
        {
            "source_kind": "production",
            "status": "production_ready",
            "model_requested": "typesafe/jev",
            "model_observed": "jev-1.13.0",
            "calibrated_definition_ids": ["next-action.v1"],
            "samples_by_definition": {"next-action.v1": {"total": 120, "heldout": 51}},
            "quality_by_definition": {
                "next-action.v1": {"status": "ok", "threshold": 0.5}
            },
        }
    )
    lock_path = tmp_path / "action.lock.json"
    manifest_path = tmp_path / "action.meta.json"
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")
    canonical = json.dumps(
        lock_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    manifest_data["lock_hash"] = (
        "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )
    manifest_data["model_requested"] = lock_data["model_requested"]
    manifest_data["dataset_hash"] = lock_data["dataset_sha"]
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    adapter = CascadeCalibrationAdapter(
        lock_path=lock_path,
        manifest_path=manifest_path,
        registry=REGISTRY,
        model="typesafe/jev",
        production=True,
        min_support=100,
        min_heldout=30,
        required_definition_ids=("next-action.v1",),
    )
    evidence = JevAnswerEvidence(
        answer_kind="ChoiceAnswer",
        answer_value="execute_query",
        confidence=0.95,
        probabilities={
            "ask_clarification": 0.01,
            "execute_query": 0.95,
            "show_result": 0.01,
            "compare": 0.01,
            "build_report": 0.01,
            "open_mini_app": 0.01,
        },
        has_probability_evidence=True,
    )

    stale = adapter.evaluate("next-action.v1", evidence, model_version="jev-1.12.0")
    current = adapter.evaluate("next-action.v1", evidence, model_version="jev-1.13.0")

    assert stale.accepted is False
    assert stale.reason == "model_version_mismatch"
    assert current.accepted is True


def test_admission_cascade_rejects_low_probability_candidate(tmp_path: Path) -> None:
    registry = QuestionRegistry.from_file(
        ROOT / "config/jev/question-definitions.admission.v1.yaml"
    )
    definition = registry.get("olympiad-profile-resolution.v1")
    candidate_id = "olympiad-profile:test-profile"
    lock_data = json.loads(LOCK.read_text(encoding="utf-8"))
    lock_data["model_requested"] = "typesafe/jev"
    lock_data["model_observed"] = ["jev-1.13.0"]
    lock_data["questions"] = {
        definition.definition_id: {
            "type": "choice",
            "instructions": definition.instructions,
            "criteria": {candidate_id: "candidate", "unresolved": "unresolved"},
            "target": 0.8,
            "measure": "top_prob",
            "threshold": 0.99,
            "status": "ok",
        }
    }
    canonical_lock = json.dumps(
        lock_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    lock_hash = "sha256:" + hashlib.sha256(canonical_lock.encode("utf-8")).hexdigest()
    manifest_data = {
        "schema_version": "andromeda-jevcal-manifest.v2",
        "artifact_id": "test-admission-candidate-lock",
        "source_kind": "production",
        "status": "production_ready",
        "lock_hash": lock_hash,
        "registry_hash": registry.content_hash(),
        "model_observed": "jev-1.13.0",
        "definition_versions": {definition.definition_id: definition.version},
        "calibrated_definition_ids": [definition.definition_id],
        "samples_by_definition": {
            definition.definition_id: {"total": 120, "heldout": 62}
        },
        "quality_by_definition": {
            definition.definition_id: {"status": "ok", "threshold": 0.99}
        },
    }
    lock_path = tmp_path / "admission.lock.json"
    manifest_path = tmp_path / "admission.lock.json.meta.json"
    lock_path.write_text(canonical_lock, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    adapter = CascadeCalibrationAdapter(
        lock_path=lock_path,
        manifest_path=manifest_path,
        registry=registry,
        model="typesafe/jev",
        production=True,
    )
    result = adapter.evaluate(
        "olympiad-profile-resolution.v1",
        JevAnswerEvidence(
            answer_kind="choice",
            answer_value=candidate_id,
            confidence=0.5,
            probabilities={
                candidate_id: 0.5,
                "unresolved": 0.5,
            },
            has_probability_evidence=True,
        ),
        model_version="jev-1.13.0",
    )

    assert result.accepted is False
    assert result.reason == "calibration_rejected"
    assert result.threshold == 0.99
