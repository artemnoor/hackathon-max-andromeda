from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pytest

from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from evals.jev.system_one_evaluator import (
    SystemOneEvaluationCase,
    SystemOneEvaluator,
)


REGISTRY = QuestionRegistry.from_file(
    Path(__file__).resolve().parents[2] / "config" / "jev" / "question-definitions.v1.yaml"
)


@dataclass
class _Usage:
    input_tokens_total: int = 12
    output_tokens_total: int = 4
    n_retries: int = 1


class _Response:
    usage = _Usage()

    def model_dump(self, *, mode: str) -> Mapping[str, object]:
        assert mode == "json"
        return {"answer": "catalog_search", "text": "private user text", "debug": {"prompt": "secret"}}


class _Client:
    def system_one(self, *, state: str, questions: Mapping[str, object], **kwargs: object) -> object:
        assert state == "Где больше математики?"
        assert "decision" in questions
        assert kwargs["provider"] == "fake"
        return _Response()


class _QuestionFactory:
    def build(self, definition: object, case: Mapping[str, object]) -> Mapping[str, object]:
        assert case["expected"] == {"intent": "catalog_search"}
        return {"decision": definition}


def test_system_one_evaluator_keeps_only_sanitized_structured_output() -> None:
    case = SystemOneEvaluationCase(
        case_id="intent-train-001",
        definition=REGISTRY.get("intent.v1"),
        input_text="Где больше математики?",
        expected={"intent": "catalog_search"},
    )

    result = SystemOneEvaluator(_Client(), _QuestionFactory()).evaluate(
        (case,), provider="fake", model="fake-v1"
    )[0]

    assert result.status == "completed"
    assert result.input_tokens == 12
    assert result.output_tokens == 4
    assert result.retry_count == 1
    assert result.malformed_retry_count is None
    assert result.sanitized_output == {"answer": "catalog_search", "text": "[REDACTED]", "debug": "[REDACTED]"}


class _FailingClient:
    def system_one(self, *, state: str, questions: Mapping[str, object], **kwargs: object) -> object:
        raise TimeoutError("provider timeout")


def test_system_one_provider_error_is_reported_only_with_explicit_allow_failures() -> None:
    case = SystemOneEvaluationCase(
        case_id="intent-train-001",
        definition=REGISTRY.get("intent.v1"),
        input_text="Где больше математики?",
        expected={"intent": "catalog_search"},
    )

    with pytest.raises(TimeoutError):
        SystemOneEvaluator(_FailingClient(), _QuestionFactory()).evaluate(
            (case,), provider="fake", model="fake-v1"
        )

    result = SystemOneEvaluator(_FailingClient(), _QuestionFactory()).evaluate(
        (case,), provider="fake", model="fake-v1", allow_failures=True
    )[0]
    assert result.status == "provider_error"
    assert result.failure_reason == "TimeoutError"
    assert result.sanitized_output is None
