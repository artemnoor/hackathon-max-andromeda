"""Safe, aggregate-only contracts for decision-model evaluation."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel


class EvaluationCase(ContractModel):
    case_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    text: str = Field(min_length=1, max_length=2000)
    expected_intent: str = Field(min_length=1, max_length=64)
    expected_metric: str | None = Field(default=None, max_length=64)
    expected_action: str = Field(min_length=1, max_length=64)


class EvaluationCaseResult(ContractModel):
    case_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    intent_match: bool
    metric_match: bool
    action_match: bool
    fallback: bool = False


class EvaluationReport(ContractModel):
    corpus_version: str = Field(min_length=1, max_length=64)
    model_version: str = Field(min_length=1, max_length=64)
    total_cases: int = Field(strict=True, ge=0, le=10_000)
    intent_accuracy: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    metric_accuracy: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    action_accuracy: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    fallback_count: int = Field(strict=True, ge=0, le=10_000)
    results: tuple[EvaluationCaseResult, ...] = Field(default=(), max_length=10_000)


__all__ = ["EvaluationCase", "EvaluationCaseResult", "EvaluationReport"]
