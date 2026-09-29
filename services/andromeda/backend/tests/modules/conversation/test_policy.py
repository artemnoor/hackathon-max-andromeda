from __future__ import annotations

from datetime import UTC, datetime, timedelta

from andromeda.modules.conversation.contracts.policy import (
    ConfidenceBucket,
    DecisionAction,
    DecisionModelSource,
)
from andromeda.modules.conversation.contracts.public import NextAction, QuerySession
from andromeda.modules.conversation.services.decision_model import RuleBasedDecisionModel
from andromeda.modules.presentation.contracts.policy import ResponseFormat, ResponseRequest
from andromeda.modules.proftest.contracts.public import ProfileScope


def _session() -> QuerySession:
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    return QuerySession(
        session_id="query-session:" + "f" * 32,
        owner_scope=ProfileScope(session_key_hash="e" * 64),
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
        next_action=NextAction.ASK_FOR_METRIC,
    )


def test_rule_based_decision_model_returns_typed_intent_and_metric() -> None:
    model = RuleBasedDecisionModel()

    intent = model.resolve_intent("Где больше математики?")
    metric = model.resolve_metric("математическая нагрузка", candidates=("math_share",))

    assert intent.intent == "analytics_query"
    assert intent.source is DecisionModelSource.DETERMINISTIC
    assert metric.metric_code == "math_share"
    assert metric.confidence is ConfidenceBucket.HIGH


def test_rule_based_decision_model_does_not_guess_unknown_metric_or_presentation() -> None:
    model = RuleBasedDecisionModel()

    metric = model.resolve_metric("какая-то неизвестная характеристика")
    action = model.choose_next_action(_session())
    presentation = model.choose_presentation(ResponseRequest())

    assert metric.metric_code is None
    assert metric.confidence is ConfidenceBucket.LOW
    assert action.decision.action is DecisionAction.ASK_CLARIFICATION
    assert presentation.response_format is ResponseFormat.TEXT
