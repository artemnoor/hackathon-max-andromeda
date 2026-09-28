"""Application result for the generic assistant transport seam."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
    AdmissionBenefitPolicyEvaluation,
)
from andromeda.modules.admission_fit.contracts.public import (
    BatchAdmissionFitRequest,
    BatchAdmissionFitResult,
)
from andromeda.modules.analytics.contracts.query import QuerySpec
from andromeda.modules.knowledge.contracts.public import KnowledgeClaimLookup
from andromeda.modules.policy.contracts.public import (
    PolicyCycleComparison,
    ResolutionTrace,
)
from andromeda.modules.presentation.contracts.envelope import ResponseEnvelope
from andromeda.shared.contracts.base import ContractModel

from .public import ConversationSlot, PolicyQueryFocus, QuerySessionId


class AssistantState(StrEnum):
    NEEDS_CLARIFICATION = "needs_clarification"
    COMPLETE = "complete"
    AMBIGUOUS = "ambiguous"


class PolicyAnswerStatus(StrEnum):
    RESOLVED = "resolved"
    POLICY_RESOLVED_DOMAIN_RESULT_UNAVAILABLE = (
        "policy_resolved_domain_result_unavailable"
    )
    SOURCE_ASSERTIONS_FOUND = "source_assertions_found"
    REVIEW_REQUIRED = "review_required"
    CONFLICT = "conflict"
    NO_MATCH = "no_match"
    BLOCKED_BY_MISSING_DATA = "blocked_by_missing_data"
    INDETERMINATE = "indeterminate"
    OUTSIDE_COVERAGE = "outside_coverage"
    HISTORICAL_STATE_UNAVAILABLE = "historical_state_unavailable"


class AssistantPolicyAnswer(ContractModel):
    focus: PolicyQueryFocus
    status: PolicyAnswerStatus
    resolution_trace: ResolutionTrace | None = None
    cycle_comparison: PolicyCycleComparison | None = None
    domain_evaluation: AdmissionBenefitPolicyEvaluation | None = None
    source_claims: tuple[KnowledgeClaimLookup, ...] = Field(default=(), max_length=20)
    reason_code: str = Field(min_length=1, max_length=96)
    missing_input_codes: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def trace_matches_status(self) -> AssistantPolicyAnswer:
        if len(self.missing_input_codes) != len(set(self.missing_input_codes)):
            raise ValueError("policy answer missing-input codes must be unique")
        if self.domain_evaluation is not None:
            if self.focus is not PolicyQueryFocus.IMPACT:
                raise ValueError("domain evaluation is only valid for impact questions")
            if self.domain_evaluation.missing_input_codes != self.missing_input_codes:
                raise ValueError(
                    "policy answer missing inputs must match the domain owner result"
                )
        if self.resolution_trace is None:
            if self.status in {
                PolicyAnswerStatus.RESOLVED,
                PolicyAnswerStatus.BLOCKED_BY_MISSING_DATA,
                PolicyAnswerStatus.POLICY_RESOLVED_DOMAIN_RESULT_UNAVAILABLE,
            }:
                raise ValueError(
                    "policy resolution status requires its structured trace"
                )
            if (
                self.status
                in {
                    PolicyAnswerStatus.SOURCE_ASSERTIONS_FOUND,
                    PolicyAnswerStatus.REVIEW_REQUIRED,
                    PolicyAnswerStatus.CONFLICT,
                    PolicyAnswerStatus.INDETERMINATE,
                }
                and not self.source_claims
            ):
                raise ValueError(
                    "claim lookup status requires exact source claim evidence"
                )
            if self.status is PolicyAnswerStatus.NO_MATCH and self.source_claims:
                raise ValueError(
                    "no-match answer cannot contain matching source claims"
                )
            return self
        expected = {
            "resolved": PolicyAnswerStatus.RESOLVED,
            "conflict": PolicyAnswerStatus.CONFLICT,
            "no_match": PolicyAnswerStatus.NO_MATCH,
            "blocked_by_missing_data": PolicyAnswerStatus.BLOCKED_BY_MISSING_DATA,
            "indeterminate": PolicyAnswerStatus.INDETERMINATE,
        }.get(self.resolution_trace.status.value)
        if (
            self.focus is PolicyQueryFocus.IMPACT
            and self.resolution_trace.status.value == "resolved"
            and self.status
            is PolicyAnswerStatus.POLICY_RESOLVED_DOMAIN_RESULT_UNAVAILABLE
        ):
            return self
        if (
            self.status is PolicyAnswerStatus.SOURCE_ASSERTIONS_FOUND
            and self.resolution_trace.status.value == "no_match"
            and self.source_claims
        ):
            return self
        if expected is None or self.status is not expected:
            raise ValueError("policy answer status must match its resolver trace")
        return self


class AssistantResult(ContractModel):
    state: AssistantState
    session_id: QuerySessionId
    revision: int = Field(strict=True, ge=1)
    question: str | None = Field(default=None, max_length=512)
    options: tuple[str, ...] = Field(default=(), max_length=20)
    missing_slots: tuple[ConversationSlot, ...] = Field(default=(), max_length=8)
    response: ResponseEnvelope | None = None
    query: QuerySpec | None = None
    admission_request: BatchAdmissionFitRequest | None = None
    admission_requests: tuple[BatchAdmissionFitRequest, ...] = Field(
        default=(), max_length=100
    )
    admission_result: BatchAdmissionFitResult | None = None
    # Internal typed use-case result; the safe user-facing projection lives in
    # ResponseEnvelope.knowledge and is the only policy shape emitted over HTTP.
    policy_answer: AssistantPolicyAnswer | None = Field(default=None, exclude=True)


__all__ = [
    "AssistantPolicyAnswer",
    "AssistantResult",
    "AssistantState",
    "PolicyAnswerStatus",
]
