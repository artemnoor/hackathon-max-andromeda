"""Deterministic replay and aggregate-only shadow evaluation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from andromeda.modules.proftest.contracts.public import ProfileScope

from ..contracts.evaluation import EvaluationCase, EvaluationCaseResult, EvaluationReport
from ..contracts.public import QuerySession
from .decision_model import RuleBasedDecisionModel
from .engine import ConversationEngine


class DecisionModelEvaluator:
    def __init__(self, model: RuleBasedDecisionModel | None = None, *, corpus_version: str = "decision-corpus.v1") -> None:
        self._model = model or RuleBasedDecisionModel()
        self._engine = ConversationEngine()
        self._corpus_version = corpus_version

    def evaluate(self, cases: tuple[EvaluationCase, ...]) -> EvaluationReport:
        results: list[EvaluationCaseResult] = []
        for case in cases:
            parsed = self._model.resolve_intent(case.text)
            metric = self._model.resolve_metric(case.text)
            session = self._engine.apply(_session(), case.text, now=_NOW + timedelta(seconds=len(results) + 1))
            action = self._model.choose_next_action(session)
            results.append(
                EvaluationCaseResult(
                    case_id=case.case_id,
                    intent_match=parsed.intent == case.expected_intent,
                    metric_match=(metric.metric_code == case.expected_metric),
                    action_match=action.decision.action.value == case.expected_action,
                    fallback=parsed.fallback_reason is not None or metric.fallback_reason is not None,
                )
            )
        total = len(results)
        return EvaluationReport(
            corpus_version=self._corpus_version,
            model_version=self._model.version,
            total_cases=total,
            intent_accuracy=_ratio(sum(item.intent_match for item in results), total),
            metric_accuracy=_ratio(sum(item.metric_match for item in results), total),
            action_accuracy=_ratio(sum(item.action_match for item in results), total),
            fallback_count=sum(item.fallback for item in results),
            results=tuple(results),
        )


def _ratio(value: int, total: int) -> Decimal:
    return Decimal("0") if total == 0 else (Decimal(value) / Decimal(total)).quantize(Decimal("0.001"))


_NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _session() -> QuerySession:
    return QuerySession(
        session_id="query-session:" + "9" * 32,
        owner_scope=ProfileScope(session_key_hash="8" * 64),
        created_at=_NOW,
        updated_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
    )


__all__ = ["DecisionModelEvaluator"]
