"""Reproducible typed policy diffs suitable for pre-approval review."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, TypeAlias

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .applicability import PolicySelection
from .approval import PolicyApprovalState
from .resolution import PolicyResolutionStatus, PolicyResolutionTraceId

PolicyDiffId = Annotated[str, StringConstraints(pattern=r"^policy-diff:[a-f0-9]{64}$")]


class PolicyDiffLayer(StrEnum):
    REVISION = "policy_revision"
    EFFECTIVE_SET = "effective_policy"


class DiffObjectState(StrEnum):
    PRESENT = "present"
    ABSENT_CONFIRMED = "absent_confirmed"
    UNKNOWN = "unknown"


class PolicyDiffStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    AMBIGUOUS = "ambiguous"


class PolicyDiffChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class PolicyDiffEntry(ContractModel):
    path: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.:-]{0,191}$")]
    kind: PolicyDiffChangeKind
    before: str | None = Field(default=None, max_length=16000)
    after: str | None = Field(default=None, max_length=16000)
    before_evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=128)
    after_evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=128)
    reason_code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]

    @model_validator(mode="after")
    def shape_matches_change(self) -> PolicyDiffEntry:
        if self.kind is PolicyDiffChangeKind.ADDED and (self.before is not None or self.after is None):
            raise ValueError("added policy diff entries require only an after value")
        if self.kind is PolicyDiffChangeKind.REMOVED and (self.before is None or self.after is not None):
            raise ValueError("removed policy diff entries require only a before value")
        if self.kind is PolicyDiffChangeKind.CHANGED and (
            self.before is None or self.after is None or self.before == self.after
        ):
            raise ValueError("changed policy diff entries require distinct before/after values")
        if self.before is None and self.before_evidence:
            raise ValueError("absent before fields cannot carry before evidence")
        if self.after is None and self.after_evidence:
            raise ValueError("absent after fields cannot carry after evidence")
        return self


class PolicyRevisionDiffSnapshot(ContractModel):
    selection: PolicySelection
    approval_state: PolicyApprovalState
    normalizer_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=128)


class EffectivePolicyDiffSnapshot(ContractModel):
    trace_id: PolicyResolutionTraceId
    university_id: str
    admission_year: int = Field(strict=True, ge=1900, le=2200)
    cycle_id: str | None = None
    cycle_revision: int | None = Field(default=None, strict=True, ge=1)
    context_fingerprint: SourceHash
    valid_as_of: datetime | None = None
    as_known_at: datetime
    status: PolicyResolutionStatus
    effective_rules: tuple[PolicySelection, ...] = Field(default=(), max_length=500)
    conflicting_rules: tuple[PolicySelection, ...] = Field(default=(), max_length=500)
    evidence: tuple[EvidenceRef, ...] = Field(max_length=128)

    @field_validator("valid_as_of", "as_known_at")
    @classmethod
    def normalize_trace_time(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("effective policy diff times must be timezone-aware")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def validate_trace_context_and_state(self) -> EffectivePolicyDiffSnapshot:
        if (self.cycle_id is None) != (self.cycle_revision is None):
            raise ValueError("effective policy diff snapshot requires a complete cycle reference")
        effective_keys = tuple(
            (item.rule_id, item.revision, item.revision_hash) for item in self.effective_rules
        )
        conflict_keys = tuple(
            (item.rule_id, item.revision, item.revision_hash) for item in self.conflicting_rules
        )
        if len(effective_keys) != len(set(effective_keys)) or len(conflict_keys) != len(set(conflict_keys)):
            raise ValueError("effective policy snapshots require unique exact rule revisions")
        if set(effective_keys) & set(conflict_keys):
            raise ValueError("an effective rule cannot simultaneously be conflicted")
        if self.status is PolicyResolutionStatus.RESOLVED and not self.effective_rules:
            raise ValueError("resolved effective policy snapshot requires selected rules")
        if self.status is PolicyResolutionStatus.CONFLICT and not self.conflicting_rules:
            raise ValueError("conflicted effective policy snapshot requires exact competitors")
        if self.status in {
            PolicyResolutionStatus.CONFLICT,
            PolicyResolutionStatus.INDETERMINATE,
            PolicyResolutionStatus.BLOCKED_BY_MISSING_DATA,
        } and self.effective_rules:
            raise ValueError("unsafe effective policy status cannot contain selected rules")
        return self


PolicyDiffSnapshot: TypeAlias = PolicyRevisionDiffSnapshot | EffectivePolicyDiffSnapshot


class PolicySemanticDiff(ContractModel):
    schema_version: str = "policy-diff.v1"
    diff_id: PolicyDiffId
    layer: PolicyDiffLayer
    status: PolicyDiffStatus
    before_state: DiffObjectState
    after_state: DiffObjectState
    before: PolicyDiffSnapshot | None = None
    after: PolicyDiffSnapshot | None = None
    changes: tuple[PolicyDiffEntry, ...] = Field(default=(), max_length=256)
    uncertainty_codes: tuple[str, ...] = Field(default=(), max_length=32)
    before_trace_id: str | None = Field(default=None, max_length=128)
    after_trace_id: str | None = Field(default=None, max_length=128)
    source_diff_hash: SourceHash | None = None

    @field_validator("uncertainty_codes")
    @classmethod
    def uncertainty_codes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("policy diff uncertainty codes must be unique")
        return value

    @model_validator(mode="after")
    def validate_revision_presence_and_state(self) -> PolicySemanticDiff:
        if (self.before_state is DiffObjectState.PRESENT) != (self.before is not None):
            raise ValueError("policy diff before snapshot must agree with explicit presence state")
        if (self.after_state is DiffObjectState.PRESENT) != (self.after is not None):
            raise ValueError("policy diff after snapshot must agree with explicit presence state")
        if self.status is PolicyDiffStatus.COMPLETE and DiffObjectState.UNKNOWN in {
            self.before_state,
            self.after_state,
        }:
            raise ValueError("complete policy diff cannot contain an unknown object state")
        if self.status is PolicyDiffStatus.INCOMPLETE and not self.uncertainty_codes:
            raise ValueError("incomplete policy diff requires explicit uncertainty")
        if self.before is None and self.after is None:
            raise ValueError("policy diff requires at least one exact revision snapshot")
        if self.layer is PolicyDiffLayer.REVISION and any(
            item is not None and not isinstance(item, PolicyRevisionDiffSnapshot)
            for item in (self.before, self.after)
        ):
            raise ValueError("revision diff layer requires policy revision snapshots")
        if self.layer is PolicyDiffLayer.EFFECTIVE_SET and any(
            item is not None and not isinstance(item, EffectivePolicyDiffSnapshot)
            for item in (self.before, self.after)
        ):
            raise ValueError("effective policy layer requires resolution trace snapshots")
        if self.before_trace_id is None and self.after_trace_id is not None:
            raise ValueError("candidate effective diff cannot exist without a baseline trace")
        return self


def policy_semantic_diff_id(
    *,
    layer: PolicyDiffLayer,
    status: PolicyDiffStatus,
    before_state: DiffObjectState,
    after_state: DiffObjectState,
    before: PolicyDiffSnapshot | None,
    after: PolicyDiffSnapshot | None,
    changes: tuple[PolicyDiffEntry, ...],
    uncertainty_codes: tuple[str, ...],
    before_trace_id: str | None,
    after_trace_id: str | None,
    source_diff_hash: SourceHash | None,
) -> PolicyDiffId:
    payload = {
        "layer": layer.value,
        "status": status.value,
        "before_state": before_state.value,
        "after_state": after_state.value,
        "before": before.model_dump(mode="json") if before else None,
        "after": after.model_dump(mode="json") if after else None,
        "changes": [item.model_dump(mode="json") for item in changes],
        "uncertainty_codes": uncertainty_codes,
        "before_trace_id": before_trace_id,
        "after_trace_id": after_trace_id,
        "source_diff_hash": source_diff_hash,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"policy-diff:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


__all__ = [
    "DiffObjectState",
    "EffectivePolicyDiffSnapshot",
    "PolicyDiffChangeKind",
    "PolicyDiffEntry",
    "PolicyDiffId",
    "PolicyDiffLayer",
    "PolicyDiffSnapshot",
    "PolicyDiffStatus",
    "PolicyRevisionDiffSnapshot",
    "PolicySemanticDiff",
    "policy_semantic_diff_id",
]
