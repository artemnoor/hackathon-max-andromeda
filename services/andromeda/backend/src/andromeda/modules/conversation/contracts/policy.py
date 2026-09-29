"""Policy seams for future Jev adapters."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import Field

from andromeda.modules.analytics.contracts.results import AnalyticsResult
from andromeda.modules.presentation.contracts.policy import (
    PresentationCapabilities,
    ResponseFormat,
    ResponseRequest,
)
from andromeda.modules.semantic.contracts.public import SemanticFeatureValue
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.versions import DECISION_POLICY_VERSION

from .public import ConversationIntent, QuerySession


class DecisionAction(StrEnum):
    ASK_CLARIFICATION = "ask_clarification"
    EXECUTE_QUERY = "execute_query"
    SHOW_RESULT = "show_result"
    COMPARE = "compare"
    BUILD_REPORT = "build_report"
    OPEN_MINI_APP = "open_mini_app"


class DecisionModelOperation(StrEnum):
    RESOLVE_INTENT = "resolve_intent"
    RESOLVE_METRIC = "resolve_metric"
    CHOOSE_NEXT_ACTION = "choose_next_action"
    CHOOSE_PRESENTATION = "choose_presentation"
    CLASSIFY_SEMANTIC_FEATURES = "classify_semantic_features"
    RESOLVE_OLYMPIAD_PROFILE = "resolve_olympiad_profile"


class DecisionModelSource(StrEnum):
    DETERMINISTIC = "deterministic"
    JEV = "jev"
    FALLBACK = "fallback"
    SHADOW = "shadow"


class ConfidenceBucket(StrEnum):
    UNAVAILABLE = "unavailable"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DataCapabilities(ContractModel):
    metrics: tuple[str, ...] = Field(default=(), max_length=100)
    has_materialized_projections: bool = True
    supports_admission_fit: bool = True
    supports_evidence: bool = True


class DecisionPolicyResult(ContractModel):
    action: DecisionAction
    question: str | None = Field(default=None, max_length=512)
    options: tuple[str, ...] = Field(default=(), max_length=20)
    reason: str = Field(min_length=1, max_length=512)
    policy_version: str = DECISION_POLICY_VERSION


class IntentDecision(ContractModel):
    operation: DecisionModelOperation = DecisionModelOperation.RESOLVE_INTENT
    intent: ConversationIntent
    source: DecisionModelSource = DecisionModelSource.DETERMINISTIC
    confidence: ConfidenceBucket = ConfidenceBucket.HIGH
    model_version: str = "rule-based.v1"
    assumptions: tuple[str, ...] = Field(default=(), max_length=8)
    fallback_reason: str | None = Field(default=None, max_length=256)


class MetricDecision(ContractModel):
    operation: DecisionModelOperation = DecisionModelOperation.RESOLVE_METRIC
    metric_code: str | None = Field(default=None, max_length=64)
    candidates: tuple[str, ...] = Field(default=(), max_length=8)
    source: DecisionModelSource = DecisionModelSource.DETERMINISTIC
    confidence: ConfidenceBucket = ConfidenceBucket.HIGH
    model_version: str = "rule-based.v1"
    assumptions: tuple[str, ...] = Field(default=(), max_length=8)
    fallback_reason: str | None = Field(default=None, max_length=256)


class NextActionDecision(ContractModel):
    operation: DecisionModelOperation = DecisionModelOperation.CHOOSE_NEXT_ACTION
    decision: DecisionPolicyResult
    source: DecisionModelSource = DecisionModelSource.DETERMINISTIC
    confidence: ConfidenceBucket = ConfidenceBucket.HIGH
    model_version: str = "rule-based.v1"
    fallback_reason: str | None = Field(default=None, max_length=256)


class PresentationDecision(ContractModel):
    operation: DecisionModelOperation = DecisionModelOperation.CHOOSE_PRESENTATION
    response_format: ResponseFormat
    template: str = Field(min_length=1, max_length=128)
    source: DecisionModelSource = DecisionModelSource.DETERMINISTIC
    confidence: ConfidenceBucket = ConfidenceBucket.HIGH
    model_version: str = "rule-based.v1"
    fallback_reason: str | None = Field(default=None, max_length=256)


class SemanticFeatureDecision(ContractModel):
    operation: DecisionModelOperation = DecisionModelOperation.CLASSIFY_SEMANTIC_FEATURES
    values: tuple[SemanticFeatureValue, ...] = Field(default=(), max_length=64)
    source: DecisionModelSource = DecisionModelSource.DETERMINISTIC
    confidence: ConfidenceBucket = ConfidenceBucket.MEDIUM
    model_version: str = "rule-based.v1"
    fallback_reason: str | None = Field(default=None, max_length=256)


class CandidateResolutionOption(ContractModel):
    candidate_id: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=512)


class CandidateResolutionDecision(ContractModel):
    operation: DecisionModelOperation = DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE
    candidate_id: str | None = Field(default=None, max_length=256)
    source: DecisionModelSource = DecisionModelSource.DETERMINISTIC
    confidence: ConfidenceBucket = ConfidenceBucket.LOW
    model_version: str = "rule-based.v1"
    fallback_reason: str | None = Field(default=None, max_length=256)


class DecisionModelPort(Protocol):
    def resolve_intent(self, text: str) -> IntentDecision: ...

    def resolve_metric(self, text: str, *, candidates: tuple[str, ...] = ()) -> MetricDecision: ...

    def choose_next_action(
        self,
        session: QuerySession,
        *,
        available_actions: tuple[DecisionAction, ...] = tuple(DecisionAction),
        capabilities: DataCapabilities | None = None,
        last_result: AnalyticsResult | None = None,
    ) -> NextActionDecision: ...

    def choose_presentation(
        self,
        request: ResponseRequest,
        *,
        capabilities: PresentationCapabilities | None = None,
    ) -> PresentationDecision: ...

    def classify_semantic_features(
        self,
        input_text: str,
        *,
        feature_codes: tuple[str, ...] = (),
    ) -> SemanticFeatureDecision: ...

    def resolve_olympiad_profile(
        self,
        text: str,
        *,
        candidates: tuple[CandidateResolutionOption, ...],
    ) -> CandidateResolutionDecision: ...


class DecisionPolicyPort(Protocol):
    def decide(
        self,
        session: QuerySession,
        *,
        available_actions: tuple[DecisionAction, ...] = tuple(DecisionAction),
        capabilities: DataCapabilities | None = None,
        last_result: AnalyticsResult | None = None,
    ) -> DecisionPolicyResult: ...


__all__ = [
    "CandidateResolutionDecision",
    "CandidateResolutionOption",
    "ConfidenceBucket",
    "DataCapabilities",
    "DecisionAction",
    "DecisionModelOperation",
    "DecisionModelPort",
    "DecisionModelSource",
    "DecisionPolicyPort",
    "DecisionPolicyResult",
    "IntentDecision",
    "MetricDecision",
    "NextActionDecision",
    "PresentationDecision",
    "SemanticFeatureDecision",
]
