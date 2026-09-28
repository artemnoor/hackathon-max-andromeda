from __future__ import annotations

import json
from pathlib import Path

from andromeda.modules.conversation.contracts.evaluation import EvaluationCase
from andromeda.modules.conversation.services.evaluation import DecisionModelEvaluator

CORPUS = Path(__file__).parents[1] / "fixtures" / "evaluation" / "decision-corpus-v1.json"


def _cases() -> tuple[EvaluationCase, ...]:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    return tuple(EvaluationCase.model_validate(item, strict=False) for item in payload["cases"])


def test_decision_replay_is_deterministic_and_aggregate_only() -> None:
    evaluator = DecisionModelEvaluator()
    first = evaluator.evaluate(_cases())
    second = evaluator.evaluate(_cases())

    assert first == second
    assert first.corpus_version == "decision-corpus.v1"
    assert first.total_cases == 8
    assert first.action_accuracy == 1
    serialized = first.model_dump(mode="json")
    assert all("text" not in result for result in serialized["results"])


def test_evaluation_report_has_no_raw_case_text_or_model_payload() -> None:
    report = DecisionModelEvaluator().evaluate(_cases())
    dumped = report.model_dump_json()

    assert "Где больше математики" not in dumped
    assert "DROP TABLE" not in dumped
