"""Typed temporal resolution request and structured per-rule trace contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.modules.admissions.contracts.admission_cycles import AdmissionCycleId
from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EducationYear, SourceHash, UniversityId

from .applicability import (
    PolicyApplicabilityContext,
    PolicyScopeMatchReason,
    PolicyScopeMatchState,
    PolicySelection,
    SelectorNodeTrace,
)
from .approval import PolicyApprovalEventReference
from .precedence import PolicyPrecedenceDecision
from .rule import (
    DomainRuleRef,
    PolicyAuthorityLevel,
    PolicyRevisionLifecycle,
    PolicyRuleId,
    PolicyScope,
)

PolicyResolutionTraceId = Annotated[
    str,
    StringConstraints(pattern=r"^policy-resolution:[a-f0-9]{64}$"),
]


class PolicyResolutionRequest(ContractModel):
    university_id: UniversityId
    admission_year: EducationYear
    context: PolicyApplicabilityContext = Field(
        default_factory=PolicyApplicabilityContext
    )
    valid_as_of: datetime | None = None
    as_known_at: datetime | None = None

    @field_validator("valid_as_of", "as_known_at")
    @classmethod
    def require_aware_times(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("policy resolution times must be timezone-aware")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def cycle_owned_fields_are_not_user_supplied(self) -> PolicyResolutionRequest:
        if len(self.context.values) > 56:
            raise ValueError(
                "policy request context must leave room for the eight cycle fields"
            )
        cycle_fields = {
            "university_id",
            "admission_year",
            "academic_year",
            "admission_cycle_id",
            "application_start_date",
            "application_end_date",
            "enrollment_start_date",
            "enrollment_end_date",
        }
        if any(item.field.value in cycle_fields for item in self.context.values):
            raise ValueError(
                "admission cycle fields must come from the approved cycle reader"
            )
        return self


class PolicyResolutionStatus(StrEnum):
    CANDIDATES_FOUND = "candidates_found"
    RESOLVED = "resolved"
    CONFLICT = "conflict"
    NO_MATCH = "no_match"
    BLOCKED_BY_MISSING_DATA = "blocked_by_missing_data"
    INDETERMINATE = "indeterminate"


class PolicyResolutionMode(StrEnum):
    APPROVED_EFFECTIVE = "approved_effective"
    HYPOTHETICAL = "hypothetical"


class PolicyResolutionBlocker(StrEnum):
    VALID_AS_OF_REQUIRED = "valid_as_of_required"
    ADMISSION_CYCLE_UNRESOLVED = "admission_cycle_unresolved"
    ADMISSION_CYCLE_IDENTITY_MISMATCH = "admission_cycle_identity_mismatch"
    ADMISSION_CYCLE_CANCELLED_OR_UNKNOWN = "admission_cycle_cancelled_or_unknown"
    PRECEDENCE_DECISION_LIMIT = "precedence_decision_limit"
    APPROVAL_PROVENANCE_INVALID = "approval_provenance_invalid"


class PolicyRuleFilterState(StrEnum):
    CANDIDATE = "candidate"
    NOT_APPLICABLE = "not_applicable"
    FUTURE = "future"
    EXPIRED = "expired"
    INDETERMINATE = "indeterminate"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"


class PolicyRuleFilterReason(StrEnum):
    SELECTOR_MATCHED = "selector_matched"
    SELECTOR_NOT_MATCHED = "selector_not_matched"
    REQUIRED_CONTEXT_UNKNOWN = "required_context_unknown"
    LIFECYCLE_NOT_APPLICABLE = "lifecycle_not_applicable"
    VALID_TIME_MISSING = "valid_time_missing"
    OUTSIDE_VALID_TIME = "outside_valid_time"
    EFFECTIVE_TIME_MISSING = "effective_time_missing"
    FUTURE_EFFECTIVE = "future_effective"
    EFFECTIVE_TIME_ENDED = "effective_time_ended"
    OWNER_PORT_NOT_REGISTERED = "owner_port_not_registered"
    OWNER_RULE_NOT_FOUND = "owner_rule_not_found"
    OWNER_LOOKUP_UNAVAILABLE = "owner_lookup_unavailable"
    ADMISSION_CYCLE_UNRESOLVED = "admission_cycle_unresolved"
    ADMISSION_CYCLE_BLOCKED = "admission_cycle_blocked"
    VALID_AS_OF_MISSING = "valid_as_of_missing"
    APPROVAL_STATE_UNRESOLVED = "approval_state_unresolved"
    SCOPE_NOT_MATCHED = "scope_not_matched"
    SCOPE_CONTEXT_UNKNOWN = "scope_context_unknown"
    LEGAL_AUTHORITY_UNRESOLVED = "legal_authority_unresolved"


class ConsideredPolicyRule(ContractModel):
    rule_id: PolicyRuleId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    revision_hash: SourceHash
    lifecycle: PolicyRevisionLifecycle
    valid_interval: tuple[datetime | None, datetime | None]
    effective_interval: tuple[datetime | None, datetime | None] | None = None
    domain_rule: DomainRuleRef
    family_id: str | None = None
    authority: PolicyAuthorityLevel | None = None
    scope: PolicyScope
    scope_state: PolicyScopeMatchState
    scope_reason: PolicyScopeMatchReason
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=128)
    approval_event: PolicyApprovalEventReference | None = None
    filter_state: PolicyRuleFilterState
    reason: PolicyRuleFilterReason
    selector_trace: tuple[SelectorNodeTrace, ...] = Field(max_length=64)
    selection: PolicySelection | None = None

    @model_validator(mode="after")
    def candidate_contains_exact_selection(self) -> ConsideredPolicyRule:
        is_candidate = self.filter_state is PolicyRuleFilterState.CANDIDATE
        if is_candidate != (self.selection is not None):
            raise ValueError(
                "only a candidate filter result may contain an exact policy selection"
            )
        if self.selection is not None and (
            self.selection.rule_id != self.rule_id
            or self.selection.revision != self.revision
            or self.selection.revision_hash != self.revision_hash
            or self.selection.domain_rule != self.domain_rule
        ):
            raise ValueError(
                "policy selection must reference this exact source-backed revision"
            )
        if self.approval_event is not None and (
            self.approval_event.rule_id != self.rule_id
            or self.approval_event.revision != self.revision
            or self.approval_event.revision_hash != self.revision_hash
        ):
            raise ValueError(
                "approval event reference must bind to this exact policy revision"
            )
        if is_candidate and self.scope_state is not PolicyScopeMatchState.MATCH:
            raise ValueError("only a scope-matched rule may become a policy candidate")
        return self


class ResolutionTraceFields(ContractModel):
    trace_version: Literal["policy-resolution-trace.v3"] = "policy-resolution-trace.v3"
    mode: PolicyResolutionMode = PolicyResolutionMode.APPROVED_EFFECTIVE
    university_id: UniversityId
    admission_year: EducationYear
    cycle_id: AdmissionCycleId | None = None
    cycle_revision: int | None = Field(default=None, strict=True, ge=1)
    cycle_evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=128)
    valid_as_of: datetime | None = None
    as_known_at: datetime
    context_fingerprint: SourceHash
    status: PolicyResolutionStatus
    blockers: tuple[PolicyResolutionBlocker, ...] = Field(default=(), max_length=16)
    considered: tuple[ConsideredPolicyRule, ...] = Field(default=(), max_length=500)
    candidates: tuple[PolicySelection, ...] = Field(default=(), max_length=500)
    effective_rules: tuple[PolicySelection, ...] = Field(default=(), max_length=500)
    conflicting_rules: tuple[PolicySelection, ...] = Field(default=(), max_length=500)
    precedence_decisions: tuple[PolicyPrecedenceDecision, ...] = Field(
        default=(), max_length=5000
    )

    @field_validator("valid_as_of", "as_known_at")
    @classmethod
    def resolution_times_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("resolution trace times must be timezone-aware")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def cycle_and_candidate_trace_are_consistent(self) -> ResolutionTraceFields:
        if (self.cycle_id is None) != (self.cycle_revision is None):
            raise ValueError("resolved cycle trace requires both cycle ID and revision")
        if self.cycle_id is None and self.cycle_evidence:
            raise ValueError("unresolved admission cycle cannot carry cycle evidence")
        if self.mode is PolicyResolutionMode.APPROVED_EFFECTIVE and any(
            item.approval_event is None for item in self.considered
        ):
            raise ValueError(
                "approved-effective traces must retain each considered approval event"
            )
        candidate_keys = tuple(
            (item.rule_id, item.revision, item.revision_hash)
            for item in self.candidates
        )
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError("resolution trace candidate selections must be unique")
        expected_candidates = tuple(
            item.selection
            for item in self.considered
            if item.filter_state is PolicyRuleFilterState.CANDIDATE
        )
        if self.candidates != expected_candidates:
            raise ValueError(
                "trace candidates must match the ordered considered-rule results"
            )
        candidates = {
            (item.rule_id, item.revision, item.revision_hash): item
            for item in self.candidates
        }
        effective_keys = tuple(
            (item.rule_id, item.revision, item.revision_hash)
            for item in self.effective_rules
        )
        conflict_keys = tuple(
            (item.rule_id, item.revision, item.revision_hash)
            for item in self.conflicting_rules
        )
        if len(effective_keys) != len(set(effective_keys)) or any(
            key not in candidates for key in effective_keys
        ):
            raise ValueError("effective rules must be unique exact candidates")
        if len(conflict_keys) != len(set(conflict_keys)) or any(
            key not in candidates for key in conflict_keys
        ):
            raise ValueError("conflicting rules must be unique exact candidates")
        if set(effective_keys) & set(conflict_keys):
            raise ValueError(
                "an exact rule revision cannot be both effective and conflicted"
            )
        if self.status is PolicyResolutionStatus.RESOLVED and not self.effective_rules:
            raise ValueError("resolved policy trace requires an effective rule set")
        if (
            self.status is PolicyResolutionStatus.CONFLICT
            and not self.conflicting_rules
        ):
            raise ValueError("conflict policy trace requires exact conflicting rules")
        if (
            self.status
            in {
                PolicyResolutionStatus.CONFLICT,
                PolicyResolutionStatus.INDETERMINATE,
                PolicyResolutionStatus.BLOCKED_BY_MISSING_DATA,
            }
            and self.effective_rules
        ):
            raise ValueError(
                "blocked, conflicted or indeterminate traces cannot expose effective rules"
            )
        return self


class ResolutionTrace(ResolutionTraceFields):
    trace_id: PolicyResolutionTraceId

    @model_validator(mode="after")
    def validate_trace_identity(self) -> ResolutionTrace:
        if self.trace_id != policy_resolution_trace_id(self):
            raise ValueError(
                "resolution trace ID does not match its structured contents"
            )
        return self


def policy_resolution_trace_id(
    trace: ResolutionTrace | ResolutionTraceFields,
) -> PolicyResolutionTraceId:
    import hashlib
    import json

    payload = trace.model_dump(mode="json", exclude={"trace_id"})
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return f"policy-resolution:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


__all__ = [
    "ConsideredPolicyRule",
    "PolicyResolutionBlocker",
    "PolicyResolutionMode",
    "PolicyResolutionRequest",
    "PolicyResolutionStatus",
    "PolicyResolutionTraceId",
    "PolicyRuleFilterReason",
    "PolicyRuleFilterState",
    "ResolutionTrace",
    "ResolutionTraceFields",
    "policy_resolution_trace_id",
]
