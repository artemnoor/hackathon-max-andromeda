from __future__ import annotations

import json
from pathlib import Path

from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from evals.jev.exporters import build_jevcal_bundle

ROOT = Path(__file__).resolve().parents[2]


def _registry() -> QuestionRegistry:
    return QuestionRegistry.from_file(
        ROOT / "config" / "jev" / "question-definitions.v1.yaml"
    )


def _rows() -> tuple[dict[str, object], ...]:
    path = ROOT / "evals" / "jev" / "corpus" / "decision-cases.v1.jsonl"
    return tuple(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    )


def test_export_matches_upstream_jevcal_input_contract() -> None:
    bundle = build_jevcal_bundle(_registry(), _rows())

    assert set(bundle.questions) == {
        "intent.v1",
        "metric.v1",
        "next-action.v1",
        "presentation.v1",
        "semantic-feature.v1",
    }
    assert all(question["type"] == "choice" for question in bundle.questions.values())
    assert all("state" in row and "labels" in row for row in bundle.rows)
    assert all("thresholds" not in question for question in bundle.questions.values())


def test_export_is_rejected_for_duplicate_case_id() -> None:
    rows = _rows()
    duplicate = rows + (rows[0],)

    try:
        build_jevcal_bundle(_registry(), duplicate)
    except ValueError as exc:
        assert "duplicate case ID" in str(exc)
    else:  # pragma: no cover - assertion keeps the failure explicit
        raise AssertionError("duplicate case ID was accepted")


def test_export_can_scope_lock_to_runtime_calibrated_decisions() -> None:
    cases = tuple(row for row in _rows() if row["definition_id"] == "next-action.v1")

    bundle = build_jevcal_bundle(_registry(), cases, definition_ids=("next-action.v1",))

    assert set(bundle.questions) == {"next-action.v1"}
    assert len(bundle.rows) == len(cases)


def test_export_supports_bounded_olympiad_profile_choices_and_unresolved() -> None:
    registry = QuestionRegistry.from_file(
        ROOT / "config" / "jev" / "question-definitions.admission.v1.yaml"
    )
    candidates = [
        {"candidate_id": "profile:a", "label": "Олимпиада — Математика"},
        {"candidate_id": "profile:b", "label": "Олимпиада — Физика"},
    ]
    rows = (
        {
            "case_id": "olympiad-profile-export-001",
            "definition_id": "olympiad-profile-resolution.v1",
            "definition_version": "olympiad-profile-resolution-definition.v1",
            "split": "train",
            "input": {"text": "олимпиада математика", "candidates": candidates},
            "expected": {"candidate_id": "profile:a"},
        },
        {
            "case_id": "olympiad-profile-export-002",
            "definition_id": "olympiad-profile-resolution.v1",
            "definition_version": "olympiad-profile-resolution-definition.v1",
            "split": "heldout",
            "input": {"text": "олимпиада без профиля", "candidates": candidates},
            "expected": {"candidate_id": None},
        },
    )

    bundle = build_jevcal_bundle(registry, rows)

    assert bundle.questions["olympiad-profile-resolution.v1"]["criteria"] == {
        "profile:a": "profile:a",
        "profile:b": "profile:b",
        "unresolved": "unresolved",
    }
    assert bundle.rows[0]["labels"] == {"olympiad-profile-resolution.v1": "profile:a"}
    assert bundle.rows[1]["labels"] == {"olympiad-profile-resolution.v1": "unresolved"}


def test_export_rejects_olympiad_label_outside_supplied_candidates() -> None:
    registry = QuestionRegistry.from_file(
        ROOT / "config" / "jev" / "question-definitions.admission.v1.yaml"
    )
    row = {
        "case_id": "olympiad-profile-export-invalid",
        "definition_id": "olympiad-profile-resolution.v1",
        "definition_version": "olympiad-profile-resolution-definition.v1",
        "split": "train",
        "input": {
            "text": "олимпиада математика",
            "candidates": [{"candidate_id": "profile:a", "label": "Математика"}],
        },
        "expected": {"candidate_id": "profile:not-supplied"},
    }

    try:
        build_jevcal_bundle(registry, (row,))
    except ValueError as exc:
        assert "outside its bounded candidate set" in str(exc)
    else:  # pragma: no cover - assertion keeps the failure explicit
        raise AssertionError("out-of-candidate label was accepted")
