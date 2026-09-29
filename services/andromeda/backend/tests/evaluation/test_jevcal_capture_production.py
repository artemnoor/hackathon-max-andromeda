from __future__ import annotations

from pathlib import Path

import pytest

from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from andromeda.modules.conversation.contracts.policy import DecisionAction
from scripts import jevcal_capture_production

ROOT = Path(__file__).resolve().parents[2]


def test_live_action_corpus_is_bounded_deterministic_and_balanced() -> None:
    registry = QuestionRegistry.from_file(ROOT / "config/jev/question-definitions.v1.yaml")

    cases = jevcal_capture_production.build_cases(registry)

    assert len(cases) == 120
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert {case["definition_id"] for case in cases} == {"next-action.v1"}
    assert {case["definition_version"] for case in cases} == {"next-action-definition.v2"}
    assert all(str(case["case_id"]).startswith("next-action-live-v2-") for case in cases)
    labels = [case["expected"]["action"] for case in cases]
    assert labels.count("ask_clarification") == 60
    assert labels.count("compare") == 30
    assert labels.count("execute_query") == 30
    assert all(
        set(case["input"]["available_actions"])
        == {action.value for action in DecisionAction}
        for case in cases
    )
    assert all("text" not in case["input"] for case in cases)


def test_corpus_holdout_uses_upstream_jevcal_split() -> None:
    from jevcal.metrics import in_holdout

    registry = QuestionRegistry.from_file(ROOT / "config/jev/question-definitions.v1.yaml")
    cases = jevcal_capture_production.build_cases(registry)

    assert all(
        (case["split"] == "heldout")
        == jevcal_capture_production._in_holdout(str(case["case_id"]))
        == in_holdout(str(case["case_id"]), 0.5, 7)
        for case in cases
    )


def test_provider_probabilities_must_cover_every_registered_action() -> None:
    labels = tuple(DecisionAction)

    with pytest.raises(jevcal_capture_production.LiveCaptureError, match="labels do not match"):
        jevcal_capture_production._validate_probabilities(
            {"ask_clarification": 0.9, "execute_query": 0.1}, labels
        )

    probabilities = {action.value: 0.01 for action in labels}
    probabilities["execute_query"] = 0.95
    validated = jevcal_capture_production._validate_probabilities(probabilities, labels)

    assert set(validated) == {action.value for action in labels}
    assert sum(validated.values()) == pytest.approx(1.0)
