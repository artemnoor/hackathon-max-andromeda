"""Immutable approval history bound to one exact policy revision hash."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import AccountId, NonEmptyText, SourceHash

from .rule import PolicyRuleId, PolicyRuleRevision

PolicyApprovalEventId = Annotated[
    str, StringConstraints(pattern=r"^policy-approval-event:[a-f0-9]{64}$")
]


class PolicyApprovalCapability(StrEnum):
    SUBMIT_REVISION = "policy.submit_revision"
    APPROVE_REVISION = "policy.approve_revision"


class PolicyApprovalEventKind(StrEnum):
    PENDING_SUBMITTED = "pending_submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class PolicyApprovalState(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    INVALID = "invalid"


class PolicyRuleSubmission(ContractModel):
    revision: PolicyRuleRevision
    submitted_by_account_id: AccountId
    reason: NonEmptyText
    submitted_at: datetime

    @field_validator("submitted_at")
    @classmethod
    def submitted_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("policy submission timestamp must be timezone-aware")
        return value.astimezone(UTC)


class PolicyApprovalCommand(ContractModel):
    rule_id: PolicyRuleId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    revision_hash: SourceHash
    kind: PolicyApprovalEventKind
    actor_account_id: AccountId
    reason: NonEmptyText
    recorded_at: datetime
    preview_fingerprint: SourceHash | None = None

    @field_validator("recorded_at")
    @classmethod
    def recorded_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("policy approval timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def only_human_actions(self) -> PolicyApprovalCommand:
        if self.kind is PolicyApprovalEventKind.PENDING_SUBMITTED:
            raise ValueError("submission events are created only with a policy revision")
        if (
            self.kind is PolicyApprovalEventKind.APPROVED
            and self.preview_fingerprint is None
        ):
            raise ValueError("policy approval requires the exact reviewer preview fingerprint")
        return self


class PolicyApprovalEvent(ContractModel):
    event_id: PolicyApprovalEventId
    rule_id: PolicyRuleId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    sequence: int = Field(strict=True, ge=1, le=2_147_483_647)
    revision_hash: SourceHash
    kind: PolicyApprovalEventKind
    actor_account_id: AccountId
    capability: PolicyApprovalCapability
    reason: NonEmptyText
    recorded_at: datetime
    preview_fingerprint: SourceHash | None = None

    @field_validator("recorded_at")
    @classmethod
    def event_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("policy approval event timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_event_binding(self) -> PolicyApprovalEvent:
        expected_capability = (
            PolicyApprovalCapability.SUBMIT_REVISION
            if self.kind is PolicyApprovalEventKind.PENDING_SUBMITTED
            else PolicyApprovalCapability.APPROVE_REVISION
        )
        if self.capability is not expected_capability:
            raise ValueError("policy approval capability does not match its event kind")
        if self.event_id != policy_approval_event_id(
            self.rule_id,
            self.revision,
            self.sequence,
            self.kind,
            self.revision_hash,
            preview_fingerprint=self.preview_fingerprint,
        ):
            raise ValueError("policy approval event ID does not match its immutable identity")
        return self


class PolicyApprovalEventReference(ContractModel):
    """Non-sensitive immutable pointer to one approval-ledger event."""

    event_id: PolicyApprovalEventId
    rule_id: PolicyRuleId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    sequence: int = Field(strict=True, ge=1, le=2_147_483_647)
    revision_hash: SourceHash
    kind: Literal[PolicyApprovalEventKind.APPROVED] = PolicyApprovalEventKind.APPROVED
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def reference_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("policy approval reference timestamp must be timezone-aware")
        return value.astimezone(UTC)


class ApprovedPolicyRevision(ContractModel):
    """Exact immutable rule revision paired with the event that approved it."""

    revision: PolicyRuleRevision
    approval_event: PolicyApprovalEvent

    @model_validator(mode="after")
    def approval_matches_exact_revision(self) -> ApprovedPolicyRevision:
        event = self.approval_event
        revision = self.revision
        if (
            event.kind is not PolicyApprovalEventKind.APPROVED
            or event.rule_id != revision.rule_id
            or event.revision != revision.revision
            or event.revision_hash != revision.content_hash
            or event.recorded_at < revision.temporal.clock.recorded_at
        ):
            raise ValueError("approval event does not approve this exact policy revision")
        return self


def policy_approval_event_reference(
    event: PolicyApprovalEvent,
) -> PolicyApprovalEventReference:
    if event.kind is not PolicyApprovalEventKind.APPROVED:
        raise ValueError("only an approval event can be referenced by effective resolution")
    return PolicyApprovalEventReference(
        event_id=event.event_id,
        rule_id=event.rule_id,
        revision=event.revision,
        sequence=event.sequence,
        revision_hash=event.revision_hash,
        kind=PolicyApprovalEventKind.APPROVED,
        recorded_at=event.recorded_at,
    )


def policy_approval_event_id(
    rule_id: PolicyRuleId,
    revision: int,
    sequence: int,
    kind: PolicyApprovalEventKind,
    revision_hash: SourceHash,
    *,
    preview_fingerprint: SourceHash | None = None,
) -> PolicyApprovalEventId:
    fields = {
        "kind": kind.value,
        "revision": revision,
        "revision_hash": revision_hash,
        "rule_id": rule_id,
        "sequence": sequence,
    }
    if preview_fingerprint is not None:
        fields["preview_fingerprint"] = preview_fingerprint
    payload = json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"policy-approval-event:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


__all__ = [
    "ApprovedPolicyRevision",
    "PolicyApprovalCapability",
    "PolicyApprovalCommand",
    "PolicyApprovalEvent",
    "PolicyApprovalEventId",
    "PolicyApprovalEventKind",
    "PolicyApprovalEventReference",
    "PolicyApprovalState",
    "PolicyRuleSubmission",
    "policy_approval_event_id",
    "policy_approval_event_reference",
]
