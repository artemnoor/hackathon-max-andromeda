"""Channel-neutral, user-safe view of source-backed policy results."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, HttpUrl, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash


class ResponseMode(StrEnum):
    DETERMINISTIC = "deterministic"
    SOURCE_BACKED_VERBALIZATION = "source_backed_verbalization"
    UNVERIFIED_FALLBACK = "unverified_fallback"


class KnowledgeAnswerState(StrEnum):
    SOURCE_ASSERTION = "source_assertion"
    POLICY_RESOLVED = "policy_resolved"
    CONFLICT = "conflict"
    NO_EVIDENCE = "no_evidence"
    INSUFFICIENT_DATA = "insufficient_data"
    OUTSIDE_COVERAGE = "outside_coverage"
    HISTORICAL_STATE_UNAVAILABLE = "historical_state_unavailable"
    REVIEW_REQUIRED = "review_required"
    UNCERTAIN = "uncertain"


class ResponseActionability(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    FUTURE_ONLY = "future_only"
    INFORMATIONAL = "informational"
    ACTION_RECOMMENDED = "action_recommended"
    ACTION_REQUIRED = "action_required"
    UNCERTAIN = "uncertain"
    BLOCKED_BY_MISSING_DATA = "blocked_by_missing_data"


class ResponseSourceCategory(StrEnum):
    OFFICIAL_DOCUMENT = "official_document"
    REGULATOR = "regulator"
    UNIVERSITY = "university"
    SECONDARY_MEDIA = "secondary_media"
    COMMUNITY = "community"
    USER_SUPPLIED = "user_supplied"
    UNKNOWN = "unknown"


class ResponseSourceReliability(StrEnum):
    PRIMARY_OFFICIAL = "primary_official"
    OFFICIAL = "official"
    TRUSTED_SECONDARY = "trusted_secondary"
    UNVERIFIED_SECONDARY = "unverified_secondary"
    COMMUNITY = "community"
    USER_SUPPLIED = "user_supplied"
    UNKNOWN = "unknown"


class ResponseClaimStage(StrEnum):
    POSSIBLE = "possible"
    ANNOUNCED = "announced"
    PROPOSAL = "proposal"
    ADOPTED = "adopted"
    PUBLISHED = "published"
    FUTURE_EFFECTIVE = "future_effective"
    EFFECTIVE = "effective"
    SUPERSEDED = "superseded"
    REPEALED = "repealed"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ResponseAssertionReviewState(StrEnum):
    REVIEWED_AS_SOURCE_ASSERTION = "reviewed_as_source_assertion"
    NEEDS_REVIEW = "needs_review"
    UNRESOLVED = "unresolved"


class ResponseScopeKind(StrEnum):
    FEDERAL = "federal"
    UNIVERSITY = "university"
    DIRECTION = "direction"
    PROGRAM = "program"
    ADMISSION_ROUTE = "admission_route"
    OTHER = "other"


class ResponseResolutionState(StrEnum):
    RESOLVED = "resolved"
    CONFLICT = "conflict"
    NO_MATCH = "no_match"
    BLOCKED = "blocked"
    INDETERMINATE = "indeterminate"
    CANDIDATES = "candidates"


class ResponseDiffStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    AMBIGUOUS = "ambiguous"


class ResponseDiffChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class RuleDisposition(StrEnum):
    SELECTED = "selected"
    CONSIDERED = "considered"
    NOT_APPLICABLE = "not_applicable"
    FUTURE = "future"
    EXPIRED = "expired"
    INCOMPLETE_SCOPE = "incomplete_scope"
    INCOMPLETE_DATA = "incomplete_data"
    UNAVAILABLE = "unavailable"
    CONFLICT = "conflict"
    UNRESOLVED = "unresolved"


class ResponseUncertainty(StrEnum):
    NO_SOURCE_ASSERTION_FOUND = "no_source_assertion_found"
    SOURCE_ASSERTION_NEEDS_REVIEW = "source_assertion_needs_review"
    SOURCE_ASSERTIONS_DISAGREE = "source_assertions_disagree"
    EFFECTIVE_DATE_UNKNOWN = "effective_date_unknown"
    SCOPE_UNKNOWN = "scope_unknown"
    DOMAIN_RESULT_UNAVAILABLE = "domain_result_unavailable"
    POLICY_CONFLICT_UNRESOLVED = "policy_conflict_unresolved"
    OUTSIDE_KNOWLEDGE_COVERAGE = "outside_knowledge_coverage"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    HISTORICAL_STATE_UNAVAILABLE = "historical_state_unavailable"


class ResponseEvidenceLocator(ContractModel):
    page: int | None = Field(default=None, strict=True, ge=1)
    section: str | None = Field(default=None, min_length=1, max_length=512)
    table: str | None = Field(default=None, min_length=1, max_length=256)
    row: int | None = Field(default=None, strict=True, ge=1)
    field: str | None = Field(default=None, min_length=1, max_length=128)
    record_key: str | None = Field(default=None, min_length=1, max_length=256)


class ResponseEvidenceReference(ContractModel):
    source_reference: str = Field(min_length=1, max_length=128)
    observation_reference: str = Field(min_length=1, max_length=128)
    snapshot_sha256: SourceHash
    url: HttpUrl
    locator: ResponseEvidenceLocator = Field(default_factory=ResponseEvidenceLocator)
    source_name: str | None = Field(default=None, min_length=1, max_length=256)
    source_category: ResponseSourceCategory = ResponseSourceCategory.UNKNOWN
    reliability: ResponseSourceReliability = ResponseSourceReliability.UNKNOWN
    published_at: datetime | None = None
    captured_at: datetime | None = None

    @field_validator("url")
    @classmethod
    def require_safe_https_url(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.scheme != "https"
            or value.username
            or value.password
            or value.port not in (None, 443)
            or value.query
            or value.fragment
        ):
            raise ValueError("public evidence URLs must be safe HTTPS references")
        return value

    @field_validator("published_at", "captured_at")
    @classmethod
    def normalize_evidence_times(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("evidence timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return None


class ResponseFact(ContractModel):
    label: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=512)
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    subject_label: str | None = Field(default=None, min_length=1, max_length=160)


class SourceAssertionView(ContractModel):
    assertion: str = Field(min_length=1, max_length=4000)
    stage: ResponseClaimStage
    review_state: ResponseAssertionReviewState
    source_name: str = Field(min_length=1, max_length=256)
    source_category: ResponseSourceCategory
    reliability: ResponseSourceReliability
    asserted_value: ResponseFact | None = None
    published_at: datetime | None = None
    announced_at: datetime | None = None
    adopted_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    evidence: tuple[ResponseEvidenceReference, ...] = Field(min_length=1, max_length=64)


class ResponseRuleReference(ContractModel):
    rule_reference: str = Field(min_length=1, max_length=128)
    revision: int = Field(strict=True, ge=1)
    revision_hash: SourceHash
    scope_kind: ResponseScopeKind
    scope_reference: str | None = Field(default=None, max_length=320)


class ConsideredRuleView(ContractModel):
    rule: ResponseRuleReference
    disposition: RuleDisposition


class RuleConflictView(ContractModel):
    rules: tuple[ResponseRuleReference, ...] = Field(min_length=2, max_length=2)
    evidence: tuple[ResponseEvidenceReference, ...] = Field(default=(), max_length=256)


class RuleExceptionView(ContractModel):
    rules: tuple[ResponseRuleReference, ...] = Field(min_length=2, max_length=2)
    selected_rule: ResponseRuleReference | None = None
    evidence: tuple[ResponseEvidenceReference, ...] = Field(default=(), max_length=256)


class ResolutionExplanation(ContractModel):
    trace_reference: str = Field(min_length=1, max_length=128)
    trace_version: str = Field(min_length=1, max_length=64)
    state: ResponseResolutionState
    valid_as_of: datetime | None = None
    selected_rules: tuple[ResponseRuleReference, ...] = Field(
        default=(), max_length=500
    )
    considered_rules: tuple[ConsideredRuleView, ...] = Field(default=(), max_length=500)
    conflicts: tuple[RuleConflictView, ...] = Field(default=(), max_length=500)
    exceptions: tuple[RuleExceptionView, ...] = Field(default=(), max_length=500)
    evidence: tuple[ResponseEvidenceReference, ...] = Field(default=(), max_length=500)
    blockers: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("valid_as_of")
    @classmethod
    def normalize_resolution_time(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("resolution valid-time must be timezone-aware")
            return value.astimezone(UTC)
        return None


class ResponsePolicyDiffEntry(ContractModel):
    path: str = Field(min_length=1, max_length=192)
    kind: ResponseDiffChangeKind
    before: str | None = Field(default=None, max_length=16_000)
    after: str | None = Field(default=None, max_length=16_000)
    before_evidence: tuple[ResponseEvidenceReference, ...] = Field(
        default=(), max_length=128
    )
    after_evidence: tuple[ResponseEvidenceReference, ...] = Field(
        default=(), max_length=128
    )
    reason_code: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def values_match_change_kind(self) -> ResponsePolicyDiffEntry:
        if self.kind is ResponseDiffChangeKind.ADDED and (
            self.before is not None or self.after is None
        ):
            raise ValueError("added policy response diff needs only an after value")
        if self.kind is ResponseDiffChangeKind.REMOVED and (
            self.before is None or self.after is not None
        ):
            raise ValueError("removed policy response diff needs only a before value")
        if self.kind is ResponseDiffChangeKind.CHANGED and (
            self.before is None or self.after is None or self.before == self.after
        ):
            raise ValueError("changed policy response diff needs distinct values")
        if self.before is None and self.before_evidence:
            raise ValueError("missing before value cannot have before evidence")
        if self.after is None and self.after_evidence:
            raise ValueError("missing after value cannot have after evidence")
        return self


class ResponseCycleComparison(ContractModel):
    before_admission_year: int = Field(strict=True, ge=1900, le=2200)
    after_admission_year: int = Field(strict=True, ge=1900, le=2200)
    before_resolution: ResolutionExplanation
    after_resolution: ResolutionExplanation
    diff_reference: str = Field(min_length=1, max_length=128)
    diff_status: ResponseDiffStatus
    changes: tuple[ResponsePolicyDiffEntry, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def years_are_ordered(self) -> ResponseCycleComparison:
        if self.before_admission_year >= self.after_admission_year:
            raise ValueError("cycle comparison years must be in ascending order")
        return self


class KnowledgeResponseSection(ContractModel):
    schema_version: Literal["knowledge-response.v1"] = "knowledge-response.v1"
    status: KnowledgeAnswerState
    actionability: ResponseActionability = ResponseActionability.UNCERTAIN
    source_assertions: tuple[SourceAssertionView, ...] = Field(
        default=(), max_length=20
    )
    known_facts: tuple[ResponseFact, ...] = Field(default=(), max_length=100)
    affected_scope: tuple[ResponseRuleReference, ...] = Field(
        default=(), max_length=500
    )
    exceptions: tuple[RuleExceptionView, ...] = Field(default=(), max_length=500)
    impact_delta: tuple[ResponseFact, ...] = Field(default=(), max_length=100)
    evidence: tuple[ResponseEvidenceReference, ...] = Field(default=(), max_length=500)
    resolution: ResolutionExplanation | None = None
    cycle_comparison: ResponseCycleComparison | None = None
    uncertainties: tuple[ResponseUncertainty, ...] = Field(default=(), max_length=16)
    missing_data: tuple[str, ...] = Field(default=(), max_length=16)
    as_known_at: datetime | None = None
    last_checked: datetime | None = None

    @field_validator("as_known_at", "last_checked")
    @classmethod
    def normalize_knowledge_times(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("knowledge response timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return None

    @field_validator("missing_data")
    @classmethod
    def missing_data_is_deduplicated(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("missing data labels must be unique")
        return value


__all__ = [
    "ConsideredRuleView",
    "KnowledgeAnswerState",
    "KnowledgeResponseSection",
    "ResolutionExplanation",
    "ResponseActionability",
    "ResponseAssertionReviewState",
    "ResponseClaimStage",
    "ResponseCycleComparison",
    "ResponseDiffChangeKind",
    "ResponseDiffStatus",
    "ResponseEvidenceLocator",
    "ResponseEvidenceReference",
    "ResponseFact",
    "ResponseMode",
    "ResponsePolicyDiffEntry",
    "ResponseResolutionState",
    "ResponseRuleReference",
    "ResponseScopeKind",
    "ResponseSourceCategory",
    "ResponseSourceReliability",
    "ResponseUncertainty",
    "RuleConflictView",
    "RuleDisposition",
    "RuleExceptionView",
    "SourceAssertionView",
]
