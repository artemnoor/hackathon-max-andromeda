"""Deterministic decision-model adapter used before an external model is approved."""

from __future__ import annotations

import logging

from andromeda.modules.analytics.contracts.results import AnalyticsResult
from andromeda.modules.presentation.contracts.policy import (
    PresentationCapabilities,
    ResponseFormat,
    ResponseRequest,
)

from ..contracts.policy import (
    CandidateResolutionDecision,
    CandidateResolutionOption,
    ConfidenceBucket,
    DataCapabilities,
    DecisionAction,
    DecisionModelOperation,
    DecisionModelPort,
    DecisionModelSource,
    IntentDecision,
    MetricDecision,
    NextActionDecision,
    PresentationDecision,
    SemanticFeatureDecision,
)
from ..contracts.public import ConversationIntent, QuerySession
from .rule_decision_policy import RuleBasedDecisionPolicy
from .rule_parser import RuleBasedQueryParser

logger = logging.getLogger("andromeda.modules.conversation.decision_model")


class RuleBasedDecisionModel(DecisionModelPort):
    """A network-free implementation with bounded outputs and safe defaults."""

    version = "rule-based.v1"

    def __init__(self) -> None:
        self._parser = RuleBasedQueryParser()
        self._policy = RuleBasedDecisionPolicy()

    def resolve_intent(self, text: str) -> IntentDecision:
        parsed = self._parser.parse(text)
        return IntentDecision(
            intent=ConversationIntent(parsed.intent),
            model_version=self.version,
            confidence=ConfidenceBucket.HIGH if parsed.intent.value != "unknown" else ConfidenceBucket.LOW,
            fallback_reason=None if parsed.intent.value != "unknown" else "unsupported_or_ambiguous_intent",
        )

    def resolve_metric(self, text: str, *, candidates: tuple[str, ...] = ()) -> MetricDecision:
        parsed = self._parser.parse(text)
        found = tuple(code for code in parsed.metric_codes if not candidates or code in candidates)
        return MetricDecision(
            metric_code=found[0] if len(found) == 1 else None,
            candidates=found,
            model_version=self.version,
            confidence=ConfidenceBucket.HIGH if len(found) == 1 else ConfidenceBucket.LOW,
            fallback_reason=None if len(found) == 1 else "metric_missing_or_ambiguous",
        )

    def choose_next_action(
        self,
        session: QuerySession,
        *,
        available_actions: tuple[DecisionAction, ...] = tuple(DecisionAction),
        capabilities: DataCapabilities | None = None,
        last_result: AnalyticsResult | None = None,
    ) -> NextActionDecision:
        decision = self._policy.decide(
            session,
            available_actions=available_actions,
            capabilities=capabilities,
            last_result=last_result,
        )
        logger.debug(
            "decision_model operation=%s source=%s action=%s policy_version=%s",
            DecisionModelOperation.CHOOSE_NEXT_ACTION.value,
            DecisionModelSource.DETERMINISTIC.value,
            decision.action.value,
            decision.policy_version,
        )
        return NextActionDecision(decision=decision, model_version=self.version)

    def choose_presentation(
        self,
        request: ResponseRequest,
        *,
        capabilities: PresentationCapabilities | None = None,
    ) -> PresentationDecision:
        caps = capabilities or PresentationCapabilities()
        result = request.result
        if request.report_requested and caps.pdf:
            response_format, template = ResponseFormat.PDF, "analytics-report"
        elif request.interactive_requested and caps.mini_app:
            response_format, template = ResponseFormat.MINI_APP, "analytics-explorer"
        elif result is None or len(result.rows) <= 1 or not caps.image:
            response_format, template = ResponseFormat.TEXT, "analytics-summary"
        elif request.comparison_requested or len(result.rows) == 2:
            response_format, template = ResponseFormat.IMAGE, "metric-comparison"
        elif len(result.rows) <= 10:
            response_format, template = ResponseFormat.IMAGE_COLLECTION, "metric-cards"
        elif caps.pdf:
            response_format, template = ResponseFormat.PDF, "analytics-report"
        else:
            response_format, template = ResponseFormat.TEXT, "analytics-summary"
        return PresentationDecision(
            response_format=response_format,
            template=template,
            model_version=self.version,
        )

    def classify_semantic_features(
        self,
        input_text: str,
        *,
        feature_codes: tuple[str, ...] = (),
    ) -> SemanticFeatureDecision:
        del input_text, feature_codes
        return SemanticFeatureDecision(
            values=(),
            source=DecisionModelSource.FALLBACK,
            confidence=ConfidenceBucket.UNAVAILABLE,
            model_version=self.version,
            fallback_reason="semantic_classification_requires_semantic_classifier_port",
        )

    def resolve_olympiad_profile(
        self,
        text: str,
        *,
        candidates: tuple[CandidateResolutionOption, ...],
    ) -> CandidateResolutionDecision:
        del text, candidates
        return CandidateResolutionDecision(
            source=DecisionModelSource.FALLBACK,
            confidence=ConfidenceBucket.UNAVAILABLE,
            model_version=self.version,
            fallback_reason="bounded_candidate_selection_unavailable",
        )


__all__ = ["RuleBasedDecisionModel"]
