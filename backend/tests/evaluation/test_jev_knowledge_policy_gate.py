from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from andromeda.infrastructure.jev.question_registry import QuestionRegistry

ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "evals" / "jev" / "manifests" / "knowledge-policy-gates.v1.json"
ADMISSION_REGISTRY_PATH = (
    ROOT / "config" / "jev" / "question-definitions.admission.v1.yaml"
)
GOLDEN_CASES_PATH = (
    ROOT
    / "evals"
    / "jev"
    / "corpus"
    / "operation-captures"
    / "olympiad-profile-resolution.v2.cases.jsonl"
)
OBSERVATIONS_PATH = (
    ROOT
    / "evals"
    / "jev"
    / "corpus"
    / "operation-captures"
    / "olympiad-profile-resolution.v2.observations.jsonl"
)


def test_knowledge_policy_has_no_unreviewed_jev_operation_registered() -> None:
    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))
    assert gate["schema_version"] == "andromeda.jev-knowledge-policy-evaluation-gate.v1"
    assert gate["registered_policy_operations"] == []
    requirements = gate["future_operation_requirements"]
    assert requirements["model_predictions_may_become_labels"] is False
    assert requirements["canonical_write_from_prediction_allowed"] is False

    registered = {
        definition.operation
        for definition in QuestionRegistry.from_file(ADMISSION_REGISTRY_PATH).all()
    }
    assert not any(
        operation.startswith(("classify_knowledge", "resolve_knowledge"))
        for operation in registered
    )


def test_reused_olympiad_corpus_is_source_labeled_and_separate_from_predictions() -> None:
    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))
    operation = gate["reused_existing_operations"][0]
    corpus_bytes = GOLDEN_CASES_PATH.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(corpus_bytes).hexdigest() == operation["golden_corpus_sha256"]
    registry_bytes = ADMISSION_REGISTRY_PATH.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(registry_bytes).hexdigest() == operation[
        "registry_artifact_sha256"
    ]
    assert operation["production_eligible"] is False
    assert operation["production_calibration_status"] == "missing_operation_specific_lock"
    assert OBSERVATIONS_PATH.is_file()
    assert GOLDEN_CASES_PATH != OBSERVATIONS_PATH

    cases = [
        json.loads(line)
        for line in corpus_bytes.decode("utf-8").splitlines()
        if line.strip()
    ]
    assert len(cases) == operation["case_count"]
    assert Counter(case["split"] for case in cases) == operation["split_counts"]
    for case in cases:
        assert case["definition_id"] == operation["definition_id"]
        assert case["definition_version"] == operation["definition_version"]
        assert "prediction" not in case
        assert "provider_response" not in case
        candidates = case["input"]["candidates"]
        gold = case["expected"]["candidate_id"]
        assert 2 <= len(candidates) <= 8
        candidate_ids = {candidate["candidate_id"] for candidate in candidates}
        assert gold is None or gold in candidate_ids
        assert case["source_provenance"]


def test_future_policy_operation_gate_is_explicit_and_fail_closed() -> None:
    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))
    requirements = gate["future_operation_requirements"]
    rollout = gate["knowledge_policy_rollout"]

    assert requirements["ground_truth_frozen_before_model_run"] is True
    assert requirements["labels_independently_authored"] is True
    assert (
        requirements[
            "minimum_golden_cases_for_matching_used_in_production_staging_or_canonical_decisions"
        ]
        == 500
    )
    assert {
        "hallucinated_relation",
        "false_match",
        "false_no_match",
        "unresolved_recall",
        "incorrect_scope_resolution",
        "incorrect_temporal_applicability",
    } <= set(requirements["required_metrics"])
    assert requirements["thresholds_must_be_approved_before_rollout"] is True
    assert requirements["unresolved_or_regressed_operation_state"] == "off_or_shadow_only"
    assert rollout["state"] == "off"
    assert rollout["shadow_prediction_enabled"] is False
    assert rollout["assisted_selection_enabled"] is False
    assert rollout["raw_source_text_in_audit"] is False
    assert rollout["applicant_profile_in_audit"] is False
    assert {
        "candidate_set_hash",
        "definition_id",
        "definition_version",
        "model_version",
        "prompt_hash",
        "reviewer_outcome",
    } <= set(rollout["future_audit_fields"])
