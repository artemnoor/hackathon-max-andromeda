"""Source-backed policy selector revision and owner-rule reference contracts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.modules.knowledge.contracts.public import (
    ClaimRevisionRef,
    EvidenceRef,
)
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .rule_ast import PolicySelectorAst
from .temporal import PolicyTemporalRevision

PolicyRuleId = Annotated[str, StringConstraints(pattern=r"^policy-rule:[a-z0-9][a-z0-9-]{0,127}$")]
PolicyFamilyId = Annotated[str, StringConstraints(pattern=r"^policy-family:[a-z0-9][a-z0-9._:-]{0,127}$")]
CanonicalDomainRuleId = Annotated[
    str,
    StringConstraints(
        pattern=r"^(?:admission-benefit|individual-achievement|admission|admission-fit):[a-z0-9][a-z0-9._:-]{0,255}$"
    ),
]


class PolicyDomainOwner(StrEnum):
    ADMISSION_BENEFITS = "admission_benefits"
    ADMISSIONS = "admissions"
    ADMISSION_FIT = "admission_fit"


class PolicyRevisionLifecycle(StrEnum):
    RUMOR = "rumor"
    HYPOTHESIS = "hypothesis"
    ANNOUNCED = "announced"
    PROPOSAL = "proposal"
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    ADOPTED = "adopted"
    PUBLISHED = "published"
    FUTURE_EFFECTIVE = "future_effective"
    EFFECTIVE = "effective"
    SUPERSEDED = "superseded"
    REPEALED = "repealed"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class PolicyAuthorityLevel(StrEnum):
    """Legal/normative force, kept separate from source reliability."""

    FEDERAL_NORMATIVE = "federal_normative"
    REGULATOR_NORMATIVE = "regulator_normative"
    UNIVERSITY_NORMATIVE = "university_normative"
    UNRESOLVED = "unresolved"


class PolicyRuleRelationKind(StrEnum):
    EXCEPTION_TO = "exception_to"
    AUTHORIZED_EXCEPTION_TO = "authorized_exception_to"
    OVERRIDES = "overrides"
    SUPERSEDES = "supersedes"
    AMENDS = "amends"
    REQUIRES = "requires"


class PolicyRuleRelation(ContractModel):
    kind: PolicyRuleRelationKind
    target_rule_id: PolicyRuleId
    target_revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    target_hash: SourceHash
    source_claim: ClaimRevisionRef
    evidence: EvidenceRef

    def identity(self) -> tuple[PolicyRuleRelationKind, str, int, str]:
        return (self.kind, self.target_rule_id, self.target_revision, self.target_hash)


class PolicyScopeLevel(StrEnum):
    FEDERAL = "federal"
    MINISTRY = "ministry"
    UNIVERSITY = "university"
    CAMPUS = "campus"
    FACULTY = "faculty"
    DEPARTMENT = "department"
    EDUCATION_LEVEL = "education_level"
    DIRECTION = "direction"
    PROGRAM = "program"
    ADMISSION_ROUTE = "admission_route"
    COMPETITION_TYPE = "competition_type"
    APPLICANT_CATEGORY = "applicant_category"
    OLYMPIAD = "olympiad"
    OLYMPIAD_PROFILE = "olympiad_profile"
    SUBJECT = "subject"


class PolicyScope(ContractModel):
    level: PolicyScopeLevel
    scope_id: Annotated[str, StringConstraints(min_length=1, max_length=320)] | None = None

    @model_validator(mode="after")
    def scope_reference_required(self) -> PolicyScope:
        if self.level is PolicyScopeLevel.FEDERAL:
            if self.scope_id is not None:
                raise ValueError("federal scope is the only scope without a scope ID")
        elif self.scope_id is None or ":" not in self.scope_id or any(
            char.isspace() for char in self.scope_id
        ):
            raise ValueError("non-federal policy scopes require a canonical namespaced ID")
        return self


class DomainRuleRef(ContractModel):
    owner_module: PolicyDomainOwner
    canonical_rule_id: CanonicalDomainRuleId
    owner_revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    owner_revision_hash: SourceHash | None = None

    @model_validator(mode="after")
    def owner_matches_rule_namespace(self) -> DomainRuleRef:
        expected_prefixes = {
            PolicyDomainOwner.ADMISSION_BENEFITS: (
                "admission-benefit:",
                "individual-achievement:",
            ),
            PolicyDomainOwner.ADMISSIONS: ("admission:",),
            PolicyDomainOwner.ADMISSION_FIT: ("admission-fit:",),
        }[self.owner_module]
        if not self.canonical_rule_id.startswith(expected_prefixes):
            raise ValueError("domain rule ID namespace does not match its owning module")
        return self


class PolicyRuleRevisionFields(ContractModel):
    rule_id: PolicyRuleId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    schema_version: Literal["policy-rule.v1", "policy-rule.v2", "policy-rule.v3"] = "policy-rule.v2"
    family_id: PolicyFamilyId | None = None
    authority: PolicyAuthorityLevel | None = None
    selector: PolicySelectorAst
    scope: PolicyScope
    domain_rule: DomainRuleRef
    lifecycle: PolicyRevisionLifecycle
    temporal: PolicyTemporalRevision
    source_claims: tuple[ClaimRevisionRef, ...] = Field(min_length=1, max_length=128)
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=128)
    relations: tuple[PolicyRuleRelation, ...] = Field(default=(), max_length=64)

    @field_validator("source_claims")
    @classmethod
    def claim_refs_are_unique(cls, value: tuple[ClaimRevisionRef, ...]) -> tuple[ClaimRevisionRef, ...]:
        refs = tuple((item.claim_id, item.revision) for item in value)
        if len(refs) != len(set(refs)):
            raise ValueError("policy source claim references must be unique")
        return value

    @model_validator(mode="after")
    def validate_temporal_and_evidence(self) -> PolicyRuleRevisionFields:
        if self.schema_version == "policy-rule.v1":
            if (
                self.family_id is not None
                or self.authority is not None
                or self.relations
                or self.domain_rule.owner_revision_hash is not None
            ):
                raise ValueError(
                    "policy-rule.v1 cannot contain family, authority, or precedence relations"
                )
        elif self.family_id is None or self.authority is None:
            raise ValueError("policy-rule.v2/v3 requires a family and legal authority classification")
        elif self.schema_version == "policy-rule.v2" and self.domain_rule.owner_revision_hash is not None:
            raise ValueError("policy-rule.v2 cannot contain an owner revision hash")
        elif self.schema_version == "policy-rule.v3" and self.domain_rule.owner_revision_hash is None:
            raise ValueError("policy-rule.v3 requires an exact domain owner revision hash")
        if self.temporal.clock.revision != self.revision:
            raise ValueError("policy temporal revision must match the rule revision")
        captured_at = self.temporal.source_milestones.captured_at
        if captured_at is None:
            raise ValueError("source-backed policy rule revisions require captured_at")
        if self.temporal.clock.recorded_at < captured_at:
            raise ValueError("policy rule knowledge time cannot precede source capture")
        evidence_keys = tuple(
            (item.source_observation_id, str(item.source_url), item.locator.model_dump_json())
            for item in self.evidence
        )
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("policy evidence references must be unique")
        relation_keys = tuple(item.identity() for item in self.relations)
        if len(relation_keys) != len(set(relation_keys)):
            raise ValueError("policy precedence relations must be unique")
        claim_refs = {(item.claim_id, item.revision) for item in self.source_claims}
        for relation in self.relations:
            if (relation.source_claim.claim_id, relation.source_claim.revision) not in claim_refs:
                raise ValueError("precedence relation claim must be part of its policy revision")
            if relation.evidence not in self.evidence:
                raise ValueError("precedence relation evidence must be part of its policy revision")
            if relation.target_rule_id == self.rule_id and relation.target_revision == self.revision:
                raise ValueError("policy precedence relations cannot target their own revision")
        effective_start = (
            self.temporal.source_milestones.effective_time.start
            if self.temporal.source_milestones.effective_time
            else None
        )
        requires_effective_time = self.lifecycle in {
            PolicyRevisionLifecycle.FUTURE_EFFECTIVE,
            PolicyRevisionLifecycle.EFFECTIVE,
            PolicyRevisionLifecycle.SUPERSEDED,
            PolicyRevisionLifecycle.REPEALED,
        }
        if requires_effective_time and effective_start is None:
            raise ValueError("this policy lifecycle requires a source-backed effective date")
        if effective_start is not None:
            if (
                self.lifecycle is PolicyRevisionLifecycle.FUTURE_EFFECTIVE
                and effective_start <= self.temporal.clock.recorded_at
            ):
                raise ValueError("future-effective policy date must follow knowledge time")
            if (
                self.lifecycle
                in {
                    PolicyRevisionLifecycle.EFFECTIVE,
                    PolicyRevisionLifecycle.SUPERSEDED,
                    PolicyRevisionLifecycle.REPEALED,
                }
                and effective_start > self.temporal.clock.recorded_at
            ):
                raise ValueError("effective policy lifecycle cannot precede its effective date")
        if any(item.inferred for item in self.evidence):
            raise ValueError("policy rule source evidence must not be inferred")
        return self


class PolicyRuleRevision(PolicyRuleRevisionFields):
    content_hash: SourceHash

    @model_validator(mode="after")
    def validate_content_hash(self) -> PolicyRuleRevision:
        if self.content_hash != policy_rule_content_hash(self):
            raise ValueError("policy rule content hash does not match its immutable revision")
        return self


def policy_rule_content_hash(revision: PolicyRuleRevision | PolicyRuleRevisionFields) -> SourceHash:
    payload = revision.model_dump(mode="json", exclude={"content_hash"})
    if payload["schema_version"] == "policy-rule.v1":
        payload.pop("family_id", None)
        payload.pop("authority", None)
        payload.pop("relations", None)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "CanonicalDomainRuleId",
    "DomainRuleRef",
    "PolicyAuthorityLevel",
    "PolicyDomainOwner",
    "PolicyFamilyId",
    "PolicyRevisionLifecycle",
    "PolicyRuleId",
    "PolicyRuleRelation",
    "PolicyRuleRelationKind",
    "PolicyRuleRevision",
    "PolicyRuleRevisionFields",
    "PolicyScope",
    "PolicyScopeLevel",
    "policy_rule_content_hash",
]
