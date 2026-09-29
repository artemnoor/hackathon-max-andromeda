from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal, TypeVar

from pydantic import BeforeValidator, Field, HttpUrl, TypeAdapter

from andromeda.modules.knowledge.contracts.public import (
    ClaimedPolicyStage,
    ClaimProposition,
    ClaimSubjectKind,
    ClaimValue,
    KnowledgeSourceKind,
    ManualClaimDraft,
    ManualClaimMetadataCorrection,
    ManualSourceRegistrationDraft,
    SourceAllowedRoute,
    SourceJurisdiction,
    SourceReliabilityTier,
)
from andromeda.modules.policy.contracts.public import PolicyRuleRevision
from andromeda.shared.contracts.ids import SourceHash

from .common import ApiModel

EnumT = TypeVar("EnumT", bound=Enum)


def _enum_from_json(enum_type: type[EnumT], value: object) -> EnumT:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        return enum_type(value)
    raise TypeError(f"{enum_type.__name__} must be a string")


def _datetime_from_json(value: object) -> object:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _date_from_json(value: object) -> object:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value


def _decimal_from_json(value: object) -> object:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    return value


JsonSourceJurisdiction = Annotated[
    SourceJurisdiction,
    BeforeValidator(lambda value: _enum_from_json(SourceJurisdiction, value)),
]
JsonSourceKind = Annotated[
    KnowledgeSourceKind,
    BeforeValidator(lambda value: _enum_from_json(KnowledgeSourceKind, value)),
]
JsonReliabilityTier = Annotated[
    SourceReliabilityTier,
    BeforeValidator(lambda value: _enum_from_json(SourceReliabilityTier, value)),
]
JsonClaimSubjectKind = Annotated[
    ClaimSubjectKind,
    BeforeValidator(lambda value: _enum_from_json(ClaimSubjectKind, value)),
]
JsonClaimedPolicyStage = Annotated[
    ClaimedPolicyStage,
    BeforeValidator(lambda value: _enum_from_json(ClaimedPolicyStage, value)),
]
JsonDateTime = Annotated[datetime, BeforeValidator(_datetime_from_json)]
JsonDate = Annotated[date, BeforeValidator(_date_from_json)]
JsonDecimal = Annotated[Decimal, BeforeValidator(_decimal_from_json), Field(strict=True)]


class SourceAllowedRouteRequest(ApiModel):
    host: str = Field(min_length=1, max_length=253)
    path_prefix: str = Field(min_length=1, max_length=1024)

    def to_contract(self) -> SourceAllowedRoute:
        return SourceAllowedRoute(host=self.host, path_prefix=self.path_prefix)


class KnowledgeSourceRegistrationRequest(ApiModel):
    source_id: str = Field(pattern=r"^source:[a-z0-9][a-z0-9-]{0,95}$")
    issuer_id: str = Field(pattern=r"^issuer:[a-z0-9][a-z0-9-]{0,95}$")
    jurisdiction: JsonSourceJurisdiction
    identity_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,95}$")
    display_name: str = Field(min_length=1, max_length=256)
    source_kind: JsonSourceKind
    reliability_tier: JsonReliabilityTier
    adapter_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,95}$")
    adapter_version: str = Field(min_length=1, max_length=64)
    start_url: HttpUrl
    allowlist: tuple[SourceAllowedRouteRequest, ...] = Field(min_length=1, max_length=64)
    poll_interval_seconds: int = Field(strict=True, ge=300, le=31_536_000)
    freshness_budget_seconds: int = Field(strict=True, ge=1, le=31_536_000)
    reason: str = Field(min_length=1, max_length=512)

    def to_draft(self) -> ManualSourceRegistrationDraft:
        return ManualSourceRegistrationDraft(
            source_id=self.source_id,
            issuer_id=self.issuer_id,
            jurisdiction=self.jurisdiction,
            identity_key=self.identity_key,
            display_name=self.display_name,
            source_kind=self.source_kind,
            reliability_tier=self.reliability_tier,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            start_url=self.start_url,
            allowlist=tuple(item.to_contract() for item in self.allowlist),
            poll_interval_seconds=self.poll_interval_seconds,
            freshness_budget_seconds=self.freshness_budget_seconds,
            reason=self.reason,
        )


class ClaimTextValueRequest(ApiModel):
    kind: Literal["text"]
    value: str = Field(min_length=1, max_length=512)


class ClaimDecimalValueRequest(ApiModel):
    kind: Literal["decimal"]
    value: JsonDecimal = Field(max_digits=16, decimal_places=6)


class ClaimBooleanValueRequest(ApiModel):
    kind: Literal["boolean"]
    value: bool


class ClaimDateValueRequest(ApiModel):
    kind: Literal["date"]
    value: JsonDate


class ClaimDateTimeValueRequest(ApiModel):
    kind: Literal["datetime"]
    value: JsonDateTime


class ClaimIdentifierValueRequest(ApiModel):
    kind: Literal["identifier"]
    value: str = Field(pattern=r"^[a-z][a-z0-9_-]*:[^\s]{1,255}$")


ClaimValueRequest = Annotated[
    ClaimTextValueRequest
    | ClaimDecimalValueRequest
    | ClaimBooleanValueRequest
    | ClaimDateValueRequest
    | ClaimDateTimeValueRequest
    | ClaimIdentifierValueRequest,
    Field(discriminator="kind"),
]


class ClaimPropositionRequest(ApiModel):
    predicate: str = Field(min_length=1, max_length=96)
    subject_kind: JsonClaimSubjectKind
    subject_id: str | None = Field(default=None, min_length=1, max_length=320)
    value: ClaimValueRequest
    unit: str | None = Field(default=None, min_length=1, max_length=64)

    def to_contract(self) -> ClaimProposition:
        value: ClaimValue = TypeAdapter(ClaimValue).validate_python(
            self.value.model_dump(mode="python")
        )
        return ClaimProposition(
            predicate=self.predicate,
            subject_kind=self.subject_kind,
            subject_id=self.subject_id,
            value=value,
            unit=self.unit,
        )


class EvidenceLocatorRequest(ApiModel):
    page: int | None = Field(default=None, strict=True, ge=1)
    table: str | None = Field(default=None, min_length=1, max_length=256)
    row: int | None = Field(default=None, strict=True, ge=1)
    section: str | None = Field(default=None, min_length=1, max_length=512)
    field: str | None = Field(default=None, min_length=1, max_length=128)
    record_key: str | None = Field(default=None, min_length=1, max_length=256)


class TemporalIntervalRequest(ApiModel):
    start: JsonDateTime | None = None
    end: JsonDateTime | None = None


class SourceMilestonesRequest(ApiModel):
    published_at: JsonDateTime | None = None
    announced_at: JsonDateTime | None = None
    adopted_at: JsonDateTime | None = None
    effective_time: TemporalIntervalRequest | None = None


class ManualClaimSubmissionRequest(ApiModel):
    source_observation_id: str = Field(pattern=r"^source-observation:[a-f0-9]{32}$")
    source_text: str = Field(min_length=1, max_length=20_000)
    assertion_text: str = Field(min_length=1, max_length=4_000)
    locator: EvidenceLocatorRequest
    proposition: ClaimPropositionRequest | None = None
    claimed_stage: JsonClaimedPolicyStage
    source_milestones: SourceMilestonesRequest
    valid_time: TemporalIntervalRequest | None = None
    reason: str = Field(min_length=1, max_length=512)
    expires_at: JsonDateTime | None = None

    def to_draft(self, *, idempotency_key: str) -> ManualClaimDraft:
        from andromeda.modules.knowledge.contracts.public import (
            EvidenceLocator,
            SourceMilestones,
            TemporalInterval,
        )

        def interval(value: TemporalIntervalRequest | None) -> TemporalInterval | None:
            if value is None:
                return None
            return TemporalInterval(start=value.start, end=value.end)

        milestones = SourceMilestones(
            published_at=self.source_milestones.published_at,
            announced_at=self.source_milestones.announced_at,
            adopted_at=self.source_milestones.adopted_at,
            effective_time=interval(self.source_milestones.effective_time),
            captured_at=None,
        )
        return ManualClaimDraft(
            source_observation_id=self.source_observation_id,
            source_text=self.source_text,
            assertion_text=self.assertion_text,
            locator=EvidenceLocator(**self.locator.model_dump(mode="python")),
            proposition=self.proposition.to_contract() if self.proposition else None,
            claimed_stage=self.claimed_stage,
            source_milestones=milestones,
            valid_time=interval(self.valid_time),
            reason=self.reason,
            expires_at=self.expires_at,
            idempotency_key=idempotency_key,
        )


class ManualClaimMetadataCorrectionRequest(ApiModel):
    expected_revision: int = Field(strict=True, ge=1)
    expected_revision_hash: SourceHash = Field(pattern=r"^[a-f0-9]{64}$")
    proposition: ClaimPropositionRequest | None = None
    claimed_stage: JsonClaimedPolicyStage
    reason: str = Field(min_length=1, max_length=512)
    expires_at: JsonDateTime | None = None

    def to_contract(self, *, claim_id: str, idempotency_key: str) -> ManualClaimMetadataCorrection:
        return ManualClaimMetadataCorrection(
            claim_id=claim_id,
            expected_revision=self.expected_revision,
            expected_revision_hash=self.expected_revision_hash,
            proposition=self.proposition.to_contract() if self.proposition else None,
            claimed_stage=self.claimed_stage,
            reason=self.reason,
            expires_at=self.expires_at,
            idempotency_key=idempotency_key,
        )


class ManualPolicyRuleCandidateRequest(ApiModel):
    revision: PolicyRuleRevision
    reason: str = Field(min_length=1, max_length=512)


class KnowledgeSourceRegistrationResponse(ApiModel):
    source_id: str
    revision: int = Field(strict=True, ge=1)
    reliability_tier: JsonReliabilityTier
    enabled: bool
    approved_by_account_id: str
    recorded_at: datetime


class KnowledgeSourceObservationResponse(ApiModel):
    source_observation_id: str
    source_id: str
    registry_revision: int = Field(strict=True, ge=1)
    snapshot_sha256: SourceHash
    captured_at: datetime
    access_mode: str
    content_type: str | None = None


class KnowledgeManualClaimResponse(ApiModel):
    claim_id: str
    revision: int = Field(strict=True, ge=1)
    review_state: str
    source_observation_id: str
    recorded_at: datetime


class ManualPolicyRuleCandidateResponse(ApiModel):
    rule_id: str
    revision: int = Field(strict=True, ge=1)
    revision_hash: SourceHash
    approval_event_id: str
    review_state: str
    submitted_by_account_id: str
    submitted_at: datetime


__all__ = [
    "KnowledgeManualClaimResponse",
    "KnowledgeSourceObservationResponse",
    "KnowledgeSourceRegistrationRequest",
    "KnowledgeSourceRegistrationResponse",
    "ManualClaimMetadataCorrectionRequest",
    "ManualClaimSubmissionRequest",
    "ManualPolicyRuleCandidateRequest",
    "ManualPolicyRuleCandidateResponse",
]
