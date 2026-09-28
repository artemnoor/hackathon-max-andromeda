"""Infrastructure-only envelopes for bounded decision-model calls."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from andromeda.modules.conversation.contracts.decision_definitions import (
    DecisionDefinitionKind,
    DecisionOutputSchema,
    DecisionPiiPolicy,
    DecisionTimeoutClass,
)
from andromeda.modules.conversation.contracts.policy import (
    DecisionModelOperation,
    DecisionModelSource,
)
from andromeda.shared.contracts.base import ContractModel


class JevFailureReason(StrEnum):
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    AUTH = "auth"
    SCHEMA = "schema"
    BUDGET = "budget"
    RATE_LIMIT = "rate_limit"
    ARTIFACT_MISSING = "artifact_missing"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CALIBRATION_REJECTED = "calibration_rejected"


class ModelIdentity(ContractModel):
    provider: str = Field(default="jev", min_length=1, max_length=64)
    model: str = Field(default="decision-model", min_length=1, max_length=128)
    model_version: str = Field(default="unknown", min_length=1, max_length=128)
    source: DecisionModelSource = DecisionModelSource.JEV
    artifact_id: str = Field(min_length=1, max_length=256)


class JevUsage(ContractModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    retry_count: int | None = Field(default=None, ge=0)
    malformed_retry_count: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)


class JevAnswerEvidence(ContractModel):
    """Bounded provider evidence passed to the optional calibration adapter."""

    answer_kind: str = Field(min_length=1, max_length=32)
    answer_value: object | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    probabilities: dict[str, float] = Field(default_factory=dict, max_length=128)
    has_probability_evidence: bool = False


class JevFailure(ContractModel):
    reason: JevFailureReason
    retryable: bool = False
    detail_code: str | None = Field(default=None, max_length=128)


class JevRequestEnvelope(ContractModel):
    """Validated request sent to a Jev-compatible transport."""

    definition_id: str = Field(min_length=1, max_length=128)
    definition_version: str = Field(min_length=1, max_length=64)
    definition_kind: DecisionDefinitionKind
    operation: DecisionModelOperation
    redacted_payload: dict[str, object] = Field(default_factory=dict, max_length=32)
    correlation_id: str = Field(min_length=1, max_length=128)
    timeout_seconds: float = Field(gt=0, le=300)
    timeout_class: DecisionTimeoutClass
    pii_policy: DecisionPiiPolicy
    output_schema: DecisionOutputSchema


class JevResponseEnvelope(ContractModel):
    """Validated transport result; ``payload`` is still untrusted model output."""

    payload: object | None = None
    identity: ModelIdentity
    usage: JevUsage = Field(default_factory=JevUsage)
    evidence: JevAnswerEvidence | None = None
    failure: JevFailure | None = None


__all__ = [
    "JevFailure",
    "JevFailureReason",
    "JevAnswerEvidence",
    "JevRequestEnvelope",
    "JevResponseEnvelope",
    "JevUsage",
    "ModelIdentity",
]
