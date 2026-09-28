"""Decision-policy wrappers for approved and shadow model paths."""

from __future__ import annotations

import hashlib
import logging

from andromeda.modules.analytics.contracts.results import AnalyticsResult

from ..contracts.policy import (
    DataCapabilities,
    DecisionAction,
    DecisionModelPort,
    DecisionPolicyPort,
    DecisionPolicyResult,
)
from ..contracts.public import ConversationIntent, QuerySession
from .rule_decision_policy import RuleBasedDecisionPolicy

logger = logging.getLogger("andromeda.modules.conversation.model_decision_policy")


class ModelBackedDecisionPolicy(DecisionPolicyPort):
    """Use a typed decision model while retaining a deterministic fallback."""

    def __init__(self, model: DecisionModelPort, fallback: DecisionPolicyPort | None = None) -> None:
        self._model = model
        self._fallback = fallback or RuleBasedDecisionPolicy()

    def decide(
        self,
        session: QuerySession,
        *,
        available_actions: tuple[DecisionAction, ...] = tuple(DecisionAction),
        capabilities: DataCapabilities | None = None,
        last_result: AnalyticsResult | None = None,
    ) -> DecisionPolicyResult:
        if session.intent is ConversationIntent.KNOWLEDGE_POLICY_QUERY:
            return self._fallback.decide(
                session,
                available_actions=available_actions,
                capabilities=capabilities,
                last_result=last_result,
            )
        try:
            decision = self._model.choose_next_action(
                session,
                available_actions=available_actions,
                capabilities=capabilities,
                last_result=last_result,
            )
            return decision.decision
        except Exception as exc:  # noqa: BLE001 - deterministic fallback handles provider-specific failures.
            logger.warning("decision_model_policy_fallback reason=%s", type(exc).__name__)
            return self._fallback.decide(
                session,
                available_actions=available_actions,
                capabilities=capabilities,
                last_result=last_result,
            )


class ShadowDecisionPolicy(DecisionPolicyPort):
    """Execute the optional model for aggregate comparison only."""

    def __init__(self, shadow_model: DecisionModelPort, deterministic: DecisionPolicyPort | None = None) -> None:
        self._shadow_model = shadow_model
        self._deterministic = deterministic or RuleBasedDecisionPolicy()

    def decide(
        self,
        session: QuerySession,
        *,
        available_actions: tuple[DecisionAction, ...] = tuple(DecisionAction),
        capabilities: DataCapabilities | None = None,
        last_result: AnalyticsResult | None = None,
    ) -> DecisionPolicyResult:
        deterministic = self._deterministic.decide(
            session,
            available_actions=available_actions,
            capabilities=capabilities,
            last_result=last_result,
        )
        if session.intent is ConversationIntent.KNOWLEDGE_POLICY_QUERY:
            return deterministic
        try:
            shadow = self._shadow_model.choose_next_action(
                session,
                available_actions=available_actions,
                capabilities=capabilities,
                last_result=last_result,
            )
            logger.info(
                "decision_shadow_comparison session_hash=%s deterministic_action=%s shadow_action=%s agreement=%s source=%s",
                _session_hash(session.session_id),
                deterministic.action.value,
                shadow.decision.action.value,
                deterministic.action is shadow.decision.action,
                shadow.source.value,
            )
        except Exception as exc:  # noqa: BLE001 - shadow failures must not affect the deterministic path.
            logger.info(
                "decision_shadow_comparison session_hash=%s deterministic_action=%s shadow_action=unavailable agreement=false fallback_reason=%s",
                _session_hash(session.session_id),
                deterministic.action.value,
                type(exc).__name__,
            )
        return deterministic


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


__all__ = ["ModelBackedDecisionPolicy", "ShadowDecisionPolicy"]
