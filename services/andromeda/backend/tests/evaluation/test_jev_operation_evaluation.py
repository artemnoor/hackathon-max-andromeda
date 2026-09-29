from __future__ import annotations

from pathlib import Path

from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from scripts import jev_operation_evaluation as evaluation

ROOT = Path(__file__).resolve().parents[2]
MAIN_REGISTRY = QuestionRegistry.from_file(
    ROOT / "config" / "jev" / "question-definitions.v1.yaml"
)
ADMISSION_REGISTRY = QuestionRegistry.from_file(
    ROOT / "config" / "jev" / "question-definitions.admission.v1.yaml"
)


def test_curated_intent_cases_are_deterministic_and_registry_labelled() -> None:
    first = evaluation.build_cases("intent.v1", MAIN_REGISTRY)
    second = evaluation.build_cases("intent.v1", MAIN_REGISTRY)

    assert first == second
    assert len(first) == 25
    assert {case["expected"]["intent"] for case in first} == {
        "catalog_search",
        "comparison",
        "admission_search",
        "recommendation",
        "unknown",
    }
    assert all(case["split"] in {"train", "heldout"} for case in first)


def test_metric_cases_use_only_registered_bounded_candidates() -> None:
    cases = evaluation.build_cases("metric.v1", MAIN_REGISTRY)

    assert len(cases) == 24
    for case in cases:
        options = evaluation._case_options(
            MAIN_REGISTRY.get("metric.v1"), case["input"]
        )
        assert case["expected"]["metric_code"] in options
        assert len(options) == 9


def test_olympiad_cases_come_from_bmstu_2026_canonical_fixture_pipeline() -> None:
    cases = evaluation.build_cases(
        "olympiad-profile-resolution.v1", ADMISSION_REGISTRY, count=120
    )

    assert len(cases) == 120
    assert len({case["case_id"] for case in cases}) == 120
    resolved = {
        case["expected"]["candidate_id"]
        for case in cases
        if case["expected"]["candidate_id"] is not None
    }
    assert len(resolved) == 11
    assert sum(case["expected"]["candidate_id"] is None for case in cases) == 10
    train_gold = {
        case["expected"]["candidate_id"]
        for case in cases
        if case["split"] == "train" and case["expected"]["candidate_id"] is not None
    }
    heldout_gold = {
        case["expected"]["candidate_id"]
        for case in cases
        if case["split"] == "heldout" and case["expected"]["candidate_id"] is not None
    }
    assert train_gold == resolved
    assert heldout_gold == resolved
    train_prefixes = (
        "Я призёр",
        "Олимпиада ",
        "У меня диплом",
        "Результат по профилю",
        "Я участвовал",
    )
    heldout_prefixes = (
        "Подскажи про",
        "Я занял призовое место",
        "Диплом ",
        "Профиль:",
        "Хочу проверить",
    )
    for case in cases:
        if case["expected"]["candidate_id"] is None:
            continue
        text = case["input"]["text"]
        if case["split"] == "train":
            assert any(text.startswith(prefix) for prefix in train_prefixes)
        else:
            assert any(text.startswith(prefix) for prefix in heldout_prefixes)
    for case in cases:
        candidates = case["input"]["candidates"]
        assert 2 <= len(candidates) <= 8
        if case["expected"]["candidate_id"] is not None:
            assert case["expected"]["candidate_id"] in {
                option["candidate_id"] for option in candidates
            }
        assert case["source_provenance"]
        assert all(
            len(source["content_sha256"]) == 64
            and all(
                character in "0123456789abcdef"
                for character in source["content_sha256"]
            )
            for source in case["source_provenance"]
        )
        assert case["split"] == evaluation._split_for(case["case_id"])


def test_olympiad_capture_uses_the_same_candidate_overlap_sanitizer_as_runtime() -> (
    None
):
    case = evaluation.build_cases(
        "olympiad-profile-resolution.v1", ADMISSION_REGISTRY, count=120
    )[0]
    definition = ADMISSION_REGISTRY.get("olympiad-profile-resolution.v1")

    request = evaluation._request_for_case(case, definition)

    assert request.redacted_payload["text"] != case["input"]["text"]
    assert request.redacted_payload["candidates"] == case["input"]["candidates"]
    assert request.timeout_seconds == 20.0


def test_live_probability_vector_must_match_this_case_options() -> None:
    validated = evaluation._validate_probabilities(
        {"profile:a": 0.8, "unresolved": 0.2}, ("profile:a", "unresolved")
    )

    assert validated == {"profile:a": 0.8, "unresolved": 0.2}
    try:
        evaluation._validate_probabilities(
            {"profile:a": 1.0}, ("profile:a", "profile:b", "unresolved")
        )
    except evaluation.OperationEvaluationError as exc:
        assert "bounded options" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("incomplete provider probabilities were accepted")
