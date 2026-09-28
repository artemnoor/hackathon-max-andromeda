"""Bounded impact results derived from exact policy traces and owner adapters."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash, UniversityId

from .applicability import PolicyApplicabilityContext
from .dependencies import PolicyDependencyEdgeId, PolicyDependencyNode
from .resolution import PolicyResolutionTraceId
from .rule import DomainRuleRef, PolicyDomainOwner
from .semantic_diff import PolicyDiffEntry, PolicyDiffId

PolicyImpactId = Annotated[str, StringConstraints(pattern=r"^policy-impact:[a-f0-9]{64}$")]


class ImpactActionability(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    FUTURE_ONLY = "future_only"
    INFORMATIONAL = "informational"
    ACTION_RECOMMENDED = "action_recommended"
    ACTION_REQUIRED = "action_required"
    UNCERTAIN = "uncertain"
    BLOCKED_BY_MISSING_DATA = "blocked_by_missing_data"


class ImpactReason(StrEnum):
    NO_EFFECTIVE_POLICY_CHANGE = "no_effective_policy_change"
    FUTURE_POLICY_ONLY = "future_policy_only"
    POLICY_CHANGE_INFORMATIONAL = "policy_change_informational"
    DOMAIN_OWNER_RECOMMENDS_ACTION = "domain_owner_recommends_action"
    DOMAIN_OWNER_REQUIRES_ACTION = "domain_owner_requires_action"
    POLICY_CONFLICT = "policy_conflict"
    CONTEXT_MISMATCH = "context_mismatch"
    DOMAIN_OWNER_RESULT_MISSING = "domain_owner_result_missing"
    RESOLUTION_BLOCKED = "resolution_blocked"
    DEPENDENCY_CYCLE = "dependency_cycle"
    DEPENDENCY_TRUNCATED = "dependency_truncated"
    UNKNOWN_APPLICABILITY = "unknown_applicability"


class DomainImpactStatus(StrEnum):
    EVALUATED = "evaluated"
    NO_DOMAIN_CHANGE = "no_domain_change"
    INSUFFICIENT_DATA = "insufficient_data"
    UNAVAILABLE = "unavailable"


class PolicyImpactStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class PolicyImpactContext(ContractModel):
    university_id: UniversityId
    admission_year: int = Field(strict=True, ge=1900, le=2200)
    context_fingerprint: SourceHash
    applicability: PolicyApplicabilityContext = Field(default_factory=PolicyApplicabilityContext)


class ImpactAffectedObject(ContractModel):
    node: PolicyDependencyNode
    relation_path: tuple[PolicyDependencyEdgeId, ...] = Field(max_length=8)
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def path_is_bounded_and_unique(self) -> ImpactAffectedObject:
        if len(self.relation_path) != len(set(self.relation_path)):
            raise ValueError("impact relation path cannot repeat an edge")
        return self


class DomainRuleImpactObservation(ContractModel):
    owner_module: PolicyDomainOwner
    before_rule: DomainRuleRef | None = None
    after_rule: DomainRuleRef | None = None
    status: DomainImpactStatus
    actionability: ImpactActionability | None = None
    changes: tuple[PolicyDiffEntry, ...] = Field(default=(), max_length=128)
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=128)
    missing_input_codes: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def owner_evidence_and_outcome_are_consistent(self) -> DomainRuleImpactObservation:
        if self.before_rule is None and self.after_rule is None:
            raise ValueError("domain impact requires at least one exact owner rule reference")
        if any(item.owner_module is not self.owner_module for item in (self.before_rule, self.after_rule) if item):
            raise ValueError("domain impact owner must match exact owner rule references")
        if self.status in {DomainImpactStatus.INSUFFICIENT_DATA, DomainImpactStatus.UNAVAILABLE}:
            if not self.missing_input_codes or self.actionability not in {
                None,
                ImpactActionability.BLOCKED_BY_MISSING_DATA,
            }:
                raise ValueError("unavailable owner result must expose missing-input codes")
        elif self.missing_input_codes:
            raise ValueError("successful owner impact cannot carry missing-input codes")
        if self.status is DomainImpactStatus.NO_DOMAIN_CHANGE and self.changes:
            raise ValueError("unchanged domain result cannot contain semantic changes")
        if self.status is DomainImpactStatus.EVALUATED and not self.evidence:
            raise ValueError("evaluated domain impact requires source evidence")
        if (
            self.actionability is ImpactActionability.BLOCKED_BY_MISSING_DATA
            and not self.missing_input_codes
        ):
            raise ValueError("blocked domain impact must identify missing inputs")
        if any(
            not item.path.startswith(f"domain_owner.{self.owner_module.value}.")
            for item in self.changes
        ):
            raise ValueError("domain owner impact fields must remain namespaced to their owner")
        return self


class PolicyImpactPreviewFields(ContractModel):
    schema_version: str = "policy-impact.v1"
    university_id: UniversityId
    admission_year: int = Field(strict=True, ge=1900, le=2200)
    context_fingerprint: SourceHash
    current_trace_id: PolicyResolutionTraceId
    candidate_trace_id: PolicyResolutionTraceId
    policy_diff_id: PolicyDiffId
    status: PolicyImpactStatus
    actionability: ImpactActionability
    reason: ImpactReason
    affected_objects: tuple[ImpactAffectedObject, ...] = Field(default=(), max_length=1000)
    domain_results: tuple[DomainRuleImpactObservation, ...] = Field(default=(), max_length=32)
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=256)
    missing_input_codes: tuple[str, ...] = Field(default=(), max_length=32)
    dependency_cycles: tuple[PolicyDependencyEdgeId, ...] = Field(default=(), max_length=1000)
    dependency_truncated: bool = False
    calculated_at: datetime

    @field_validator("calculated_at")
    @classmethod
    def calculated_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("impact calculated_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def fail_closed_impact_has_a_reason(self) -> PolicyImpactPreviewFields:
        if len(set(self.missing_input_codes)) != len(self.missing_input_codes):
            raise ValueError("impact missing-input codes must be unique")
        if self.actionability is ImpactActionability.BLOCKED_BY_MISSING_DATA and not self.missing_input_codes:
            raise ValueError("blocked impact must identify missing inputs")
        if self.reason is ImpactReason.DEPENDENCY_TRUNCATED and not self.dependency_truncated:
            raise ValueError("truncation reason requires an explicitly truncated dependency traversal")
        if self.dependency_truncated and self.actionability not in {
            ImpactActionability.UNCERTAIN,
            ImpactActionability.BLOCKED_BY_MISSING_DATA,
        }:
            raise ValueError("truncated impact cannot claim complete actionability")
        return self


class PolicyImpactPreview(PolicyImpactPreviewFields):
    impact_id: PolicyImpactId

    @model_validator(mode="after")
    def content_addressed_result(self) -> PolicyImpactPreview:
        if self.impact_id != policy_impact_id(self):
            raise ValueError("policy impact ID does not match its immutable result")
        return self


def policy_impact_id(preview: PolicyImpactPreviewFields) -> PolicyImpactId:
    payload = preview.model_dump(mode="json", exclude={"impact_id"})
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"policy-impact:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


__all__ = [
    "DomainImpactStatus",
    "DomainRuleImpactObservation",
    "ImpactActionability",
    "ImpactAffectedObject",
    "ImpactReason",
    "PolicyImpactContext",
    "PolicyImpactId",
    "PolicyImpactPreview",
    "PolicyImpactPreviewFields",
    "PolicyImpactStatus",
    "policy_impact_id",
]
