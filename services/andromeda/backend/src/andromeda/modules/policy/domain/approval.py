"""Approval ledger invariants for exact immutable policy revisions."""

from __future__ import annotations

from datetime import datetime

from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalCapability,
    PolicyApprovalEvent,
    PolicyApprovalEventKind,
    PolicyApprovalState,
    policy_approval_event_id,
)
from andromeda.modules.policy.contracts.rule import PolicyRuleRevision


def create_pending_submission_event(
    revision: PolicyRuleRevision,
    *,
    actor_account_id: str,
    reason: str,
    recorded_at: datetime,
) -> PolicyApprovalEvent:
    kind = PolicyApprovalEventKind.PENDING_SUBMITTED
    return PolicyApprovalEvent(
        event_id=policy_approval_event_id(
            revision.rule_id, revision.revision, 1, kind, revision.content_hash
        ),
        rule_id=revision.rule_id,
        revision=revision.revision,
        sequence=1,
        revision_hash=revision.content_hash,
        kind=kind,
        actor_account_id=actor_account_id,
        capability=PolicyApprovalCapability.SUBMIT_REVISION,
        reason=reason,
        recorded_at=recorded_at,
    )


def create_approval_event(
    *,
    rule_id: str,
    revision: int,
    revision_hash: str,
    sequence: int,
    kind: PolicyApprovalEventKind,
    actor_account_id: str,
    reason: str,
    recorded_at: datetime,
    preview_fingerprint: str | None = None,
) -> PolicyApprovalEvent:
    if kind is PolicyApprovalEventKind.PENDING_SUBMITTED:
        raise ValueError("pending submission event is created atomically with the rule revision")
    return PolicyApprovalEvent(
        event_id=policy_approval_event_id(
            rule_id,
            revision,
            sequence,
            kind,
            revision_hash,
            preview_fingerprint=preview_fingerprint,
        ),
        rule_id=rule_id,
        revision=revision,
        sequence=sequence,
        revision_hash=revision_hash,
        kind=kind,
        actor_account_id=actor_account_id,
        capability=PolicyApprovalCapability.APPROVE_REVISION,
        reason=reason,
        recorded_at=recorded_at,
        preview_fingerprint=preview_fingerprint,
    )


def derive_approval_state(
    events: tuple[PolicyApprovalEvent, ...],
    *,
    rule_id: str,
    revision: int,
    revision_hash: str,
) -> PolicyApprovalState:
    if not events:
        return PolicyApprovalState.NOT_SUBMITTED
    ordered = tuple(sorted(events, key=lambda item: item.sequence))
    for index, event in enumerate(ordered, start=1):
        if (
            event.rule_id != rule_id
            or event.revision != revision
            or event.revision_hash != revision_hash
            or event.sequence != index
        ):
            return PolicyApprovalState.INVALID
        if index == 1:
            if event.kind is not PolicyApprovalEventKind.PENDING_SUBMITTED:
                return PolicyApprovalState.INVALID
        else:
            if ordered[index - 2].kind is not PolicyApprovalEventKind.PENDING_SUBMITTED:
                return PolicyApprovalState.INVALID
            if event.kind is PolicyApprovalEventKind.PENDING_SUBMITTED:
                return PolicyApprovalState.INVALID
            if event.recorded_at <= ordered[index - 2].recorded_at:
                return PolicyApprovalState.INVALID
    current = ordered[-1].kind
    return {
        PolicyApprovalEventKind.PENDING_SUBMITTED: PolicyApprovalState.PENDING,
        PolicyApprovalEventKind.APPROVED: PolicyApprovalState.APPROVED,
        PolicyApprovalEventKind.REJECTED: PolicyApprovalState.REJECTED,
        PolicyApprovalEventKind.WITHDRAWN: PolicyApprovalState.WITHDRAWN,
    }[current]


def validate_approval_append(
    events: tuple[PolicyApprovalEvent, ...],
    event: PolicyApprovalEvent,
    *,
    revision_hash: str,
) -> None:
    state = derive_approval_state(
        events,
        rule_id=event.rule_id,
        revision=event.revision,
        revision_hash=revision_hash,
    )
    if event.revision_hash != revision_hash:
        raise ValueError("approval event is bound to a stale policy revision hash")
    if state is PolicyApprovalState.NOT_SUBMITTED:
        raise ValueError("policy revision has no initial pending-submission event")
    if state is not PolicyApprovalState.PENDING:
        raise ValueError("policy approval history is terminal or invalid")
    if event.sequence != len(events) + 1:
        raise ValueError("policy approval event sequence must append consecutively")
    if event.kind is PolicyApprovalEventKind.PENDING_SUBMITTED:
        raise ValueError("only policy revision submission may create the pending event")
    if events and event.recorded_at <= events[-1].recorded_at:
        raise ValueError("policy approval event times must increase")


__all__ = [
    "create_approval_event",
    "create_pending_submission_event",
    "derive_approval_state",
    "validate_approval_append",
]
