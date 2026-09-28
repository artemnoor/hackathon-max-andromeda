"""Exact, auditable human review contracts for staged knowledge candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import AccountId, NonEmptyText, SourceHash

from .claims import ChangeEvent, ChangeEventReviewState, Claim, ClaimReviewState
from .evidence import EvidenceRef
from .temporal import TemporalInterval

KnowledgeReviewItemId = Annotated[
    str, StringConstraints(pattern=r"^knowledge-review:[a-f0-9]{64}$")
]
KnowledgeReviewActionId = Annotated[
    str, StringConstraints(pattern=r"^knowledge-review-action:[a-f0-9]{64}$")
]
ReviewIdempotencyKey = Annotated[
    str, StringConstraints(pattern=r"^review-idempotency:[a-f0-9]{64}$")
]
ReviewDiffReference = Annotated[
    str, StringConstraints(pattern=r"^(knowledge|policy)-diff:[a-f0-9]{64}$")
]
ReviewImpactReference = Annotated[
    str, StringConstraints(pattern=r"^policy-impact:[a-f0-9]{64}$")
]
ReviewPolicyTraceReference = Annotated[
    str, StringConstraints(pattern=r"^policy-resolution:[a-f0-9]{64}$")
]
PolicyApprovalEventReference = Annotated[
    str, StringConstraints(pattern=r"^policy-approval-event:[a-f0-9]{64}$")
]


class KnowledgeReviewTargetKind(StrEnum):
    CLAIM = "claim"
    CHANGE_EVENT = "change_event"
    POLICY_RULE = "policy_rule"


class KnowledgeReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    MERGE = "merge"
    RESOLVE_IDENTITY = "resolve_identity"
    MARK_UNRESOLVED = "mark_unresolved"
    MARK_DUPLICATE = "mark_duplicate"


class KnowledgeReviewCapability(StrEnum):
    REVIEW_CANDIDATE = "knowledge.review_candidate"
    EDIT_CANDIDATE = "knowledge.edit_candidate"
    RESOLVE_IDENTITY = "knowledge.resolve_identity"


class KnowledgeReviewStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    DUPLICATE = "duplicate"
    BLOCKED = "blocked"


class KnowledgeReviewTargetRef(ContractModel):
    kind: KnowledgeReviewTargetKind
    object_id: Annotated[str, StringConstraints(min_length=1, max_length=140)]
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    revision_hash: SourceHash

    @model_validator(mode="after")
    def id_prefix_matches_target_kind(self) -> KnowledgeReviewTargetRef:
        prefixes = {
            KnowledgeReviewTargetKind.CLAIM: "claim:",
            KnowledgeReviewTargetKind.CHANGE_EVENT: "change-event:",
            KnowledgeReviewTargetKind.POLICY_RULE: "policy-rule:",
        }
        if not self.object_id.startswith(prefixes[self.kind]):
            raise ValueError("review target ID prefix does not match its target kind")
        return self


class KnowledgeReviewItem(ContractModel):
    """Read model; owner modules supply the exact candidate and structured previews."""

    item_id: KnowledgeReviewItemId
    target: KnowledgeReviewTargetRef
    status: KnowledgeReviewStatus
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=128)
    extraction_rationale: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    confidence: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(1))
    proposed_relations: tuple[KnowledgeReviewTargetRef, ...] = Field(default=(), max_length=64)
    current_canonical: KnowledgeReviewTargetRef | None = None
    diff_reference: ReviewDiffReference | None = None
    impact_reference: ReviewImpactReference | None = None
    resolution_trace_ids: tuple[ReviewPolicyTraceReference, ...] = Field(default=(), max_length=2)
    conflict_id: Annotated[str, StringConstraints(pattern=r"^knowledge-conflict:[a-f0-9]{64}$")] | None = None
    effective_time: TemporalInterval | None = None
    scope_ids: tuple[Annotated[str, StringConstraints(min_length=1, max_length=320)], ...] = Field(
        default=(), max_length=64
    )
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review item created_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def exact_policy_preview_refs_are_required(self) -> KnowledgeReviewItem:
        if (
            self.target.kind is KnowledgeReviewTargetKind.POLICY_RULE
            and (
                self.diff_reference is None
                or self.impact_reference is None
                or len(self.resolution_trace_ids) != 2
            )
        ):
            raise ValueError("policy review items require diff, impact, and both exact traces")
        if self.item_id != review_item_id(self.target):
            raise ValueError("review item ID does not match its exact target revision")
        if len(set(self.scope_ids)) != len(self.scope_ids):
            raise ValueError("review item scope IDs must be unique")
        if len({item.model_dump_json() for item in self.proposed_relations}) != len(
            self.proposed_relations
        ):
            raise ValueError("review item proposed relations must be unique")
        return self


class KnowledgeReviewCommand(ContractModel):
    target: KnowledgeReviewTargetRef
    action: KnowledgeReviewAction
    actor_account_id: AccountId
    reason: NonEmptyText
    idempotency_key: ReviewIdempotencyKey
    recorded_at: datetime
    related_target: KnowledgeReviewTargetRef | None = None
    edited_claim: Claim | None = None
    edited_change_event: ChangeEvent | None = None
    policy_preview_fingerprint: SourceHash | None = None

    @field_validator("recorded_at")
    @classmethod
    def command_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review action time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def action_payload_matches_exact_target(self) -> KnowledgeReviewCommand:
        if self.target.kind is KnowledgeReviewTargetKind.POLICY_RULE:
            if self.action not in {KnowledgeReviewAction.APPROVE, KnowledgeReviewAction.REJECT}:
                raise ValueError("policy revisions support only policy-owned approve/reject decisions")
            if self.action is KnowledgeReviewAction.APPROVE and self.policy_preview_fingerprint is None:
                raise ValueError("policy approval requires the exact reviewer preview fingerprint")
            if (
                self.related_target is not None
                or self.edited_claim is not None
                or self.edited_change_event is not None
            ):
                raise ValueError("policy decisions cannot include knowledge candidate edit payloads")
            return self
        if self.policy_preview_fingerprint is not None:
            raise ValueError("policy preview fingerprints apply only to policy-rule reviews")
        edit_actions = {
            KnowledgeReviewAction.EDIT,
            KnowledgeReviewAction.RESOLVE_IDENTITY,
        }
        duplicate_actions = {
            KnowledgeReviewAction.MERGE,
            KnowledgeReviewAction.MARK_DUPLICATE,
        }
        has_edit = self.edited_claim is not None or self.edited_change_event is not None
        if self.action is KnowledgeReviewAction.RESOLVE_IDENTITY and (
            self.target.kind is not KnowledgeReviewTargetKind.CLAIM
        ):
            raise ValueError("identity resolution is available only for typed source claims")
        if self.action in edit_actions:
            if self.target.kind is KnowledgeReviewTargetKind.CLAIM:
                if self.edited_claim is None or self.edited_change_event is not None:
                    raise ValueError("claim edit requires exactly one replacement claim candidate")
                if self.edited_claim.claim_id != self.target.object_id:
                    raise ValueError("edited claim must preserve source-assertion identity")
                if self.edited_claim.clock.revision != self.target.revision + 1:
                    raise ValueError("edited claim revision must append to the exact reviewed candidate")
                if self.edited_claim.review_state not in {
                    ClaimReviewState.UNREVIEWED,
                    ClaimReviewState.NEEDS_REVIEW,
                }:
                    raise ValueError("edited claim must return to review-required state")
                if self.action is KnowledgeReviewAction.RESOLVE_IDENTITY and (
                    self.edited_claim.proposition is None
                    or self.edited_claim.proposition.subject_id is None
                ):
                    raise ValueError("identity resolution requires a canonical proposition subject")
            else:
                if self.edited_change_event is None or self.edited_claim is not None:
                    raise ValueError("change-event edit requires exactly one replacement event")
                if self.edited_change_event.change_event_id != self.target.object_id:
                    raise ValueError("edited change event must preserve its canonical event identity")
                if self.edited_change_event.clock.revision != self.target.revision + 1:
                    raise ValueError("edited event revision must append to the exact reviewed candidate")
                if self.edited_change_event.review_state is not ChangeEventReviewState.NEEDS_REVIEW:
                    raise ValueError("edited change event must return to review-required state")
        elif has_edit:
            raise ValueError("only edit and identity-resolution actions may include replacement candidates")
        if self.action in duplicate_actions:
            if self.related_target is None or self.related_target.kind is not self.target.kind:
                raise ValueError("merge/duplicate actions require a same-kind exact target")
            if self.related_target.object_id == self.target.object_id:
                raise ValueError("a candidate cannot be merged into itself")
        elif self.related_target is not None:
            raise ValueError("related target is only valid for merge/duplicate actions")
        return self


class KnowledgeReviewActionEvent(ContractModel):
    event_id: KnowledgeReviewActionId
    idempotency_key: ReviewIdempotencyKey
    request_fingerprint: SourceHash
    target: KnowledgeReviewTargetRef
    action: KnowledgeReviewAction
    result: KnowledgeReviewTargetRef
    related_target: KnowledgeReviewTargetRef | None = None
    actor_account_id: AccountId
    capability: KnowledgeReviewCapability
    reason: NonEmptyText
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def event_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review event time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def event_refs_match_command(self) -> KnowledgeReviewActionEvent:
        if self.target.kind is KnowledgeReviewTargetKind.POLICY_RULE:
            raise ValueError("policy approval events remain owned by the policy module")
        if self.result.kind is not self.target.kind:
            raise ValueError("review result must preserve the target kind")
        if self.result.object_id != self.target.object_id or self.result.revision != self.target.revision + 1:
            raise ValueError("review event result must append exactly one revision of its target")
        duplicate_action = self.action in {
            KnowledgeReviewAction.MERGE,
            KnowledgeReviewAction.MARK_DUPLICATE,
        }
        if duplicate_action and (
            self.related_target is None
            or self.related_target.kind is not self.target.kind
            or self.related_target.object_id == self.target.object_id
        ):
            raise ValueError("duplicate review events require a distinct same-kind target")
        if not duplicate_action and self.related_target is not None:
            raise ValueError("non-duplicate review events cannot carry a related target")
        capability = _required_capability(self.action)
        if self.capability is not capability:
            raise ValueError("review event capability does not match its action")
        if self.event_id != knowledge_review_action_event_id(
            idempotency_key=self.idempotency_key,
            request_fingerprint=self.request_fingerprint,
            target=self.target,
            action=self.action,
            result=self.result,
            related_target=self.related_target,
            actor_account_id=self.actor_account_id,
            capability=self.capability,
            reason=self.reason,
            recorded_at=self.recorded_at,
        ):
            raise ValueError("review event ID does not match its immutable action")
        return self


class KnowledgeReviewPolicyDecisionStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class KnowledgeReviewPolicyDecision(ContractModel):
    """Receipt for a decision recorded only in the policy-owned approval ledger."""

    target: KnowledgeReviewTargetRef
    action: KnowledgeReviewAction
    status: KnowledgeReviewPolicyDecisionStatus
    approval_event_id: PolicyApprovalEventReference
    sequence: int = Field(strict=True, ge=2, le=2_147_483_647)
    actor_account_id: AccountId
    reason: NonEmptyText
    recorded_at: datetime
    preview_fingerprint: SourceHash | None = None

    @field_validator("recorded_at")
    @classmethod
    def decision_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("policy decision time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def decision_matches_exact_policy_target(self) -> KnowledgeReviewPolicyDecision:
        if self.target.kind is not KnowledgeReviewTargetKind.POLICY_RULE:
            raise ValueError("policy decision receipt requires an exact policy rule target")
        expected_status = {
            KnowledgeReviewAction.APPROVE: KnowledgeReviewPolicyDecisionStatus.APPROVED,
            KnowledgeReviewAction.REJECT: KnowledgeReviewPolicyDecisionStatus.REJECTED,
        }.get(self.action)
        if expected_status is None or self.status is not expected_status:
            raise ValueError("policy decision receipt status must match approve/reject action")
        if (
            self.action is KnowledgeReviewAction.APPROVE
            and self.preview_fingerprint is None
        ):
            raise ValueError("approved policy decision receipt must bind its preview fingerprint")
        return self


def review_item_id(target: KnowledgeReviewTargetRef) -> KnowledgeReviewItemId:
    return f"knowledge-review:{_digest(target.model_dump(mode='json'))}"


def knowledge_review_target_hash(candidate: Claim | ChangeEvent) -> SourceHash:
    return _digest(candidate.model_dump(mode="json"))


def knowledge_review_target_ref(candidate: Claim | ChangeEvent) -> KnowledgeReviewTargetRef:
    if isinstance(candidate, Claim):
        kind = KnowledgeReviewTargetKind.CLAIM
        object_id = candidate.claim_id
    else:
        kind = KnowledgeReviewTargetKind.CHANGE_EVENT
        object_id = candidate.change_event_id
    return KnowledgeReviewTargetRef(
        kind=kind,
        object_id=object_id,
        revision=candidate.clock.revision,
        revision_hash=knowledge_review_target_hash(candidate),
    )


def knowledge_review_action_event_id(
    *,
    idempotency_key: ReviewIdempotencyKey,
    request_fingerprint: SourceHash,
    target: KnowledgeReviewTargetRef,
    action: KnowledgeReviewAction,
    result: KnowledgeReviewTargetRef,
    related_target: KnowledgeReviewTargetRef | None,
    actor_account_id: AccountId,
    capability: KnowledgeReviewCapability,
    reason: str,
    recorded_at: datetime,
) -> KnowledgeReviewActionId:
    payload = {
        "action": action.value,
        "actor_account_id": actor_account_id,
        "capability": capability.value,
        "idempotency_key": idempotency_key,
        "reason": reason,
        "recorded_at": recorded_at.astimezone(UTC).isoformat(),
        "request_fingerprint": request_fingerprint,
        "related_target": related_target.model_dump(mode="json") if related_target else None,
        "result": result.model_dump(mode="json"),
        "target": target.model_dump(mode="json"),
    }
    return f"knowledge-review-action:{_digest(payload)}"


def knowledge_review_command_fingerprint(command: KnowledgeReviewCommand) -> SourceHash:
    payload = command.model_dump(mode="json", exclude={"idempotency_key"})
    return _digest(payload)


def _required_capability(action: KnowledgeReviewAction) -> KnowledgeReviewCapability:
    if action in {
        KnowledgeReviewAction.EDIT,
        KnowledgeReviewAction.RESOLVE_IDENTITY,
    }:
        return (
            KnowledgeReviewCapability.RESOLVE_IDENTITY
            if action is KnowledgeReviewAction.RESOLVE_IDENTITY
            else KnowledgeReviewCapability.EDIT_CANDIDATE
        )
    return KnowledgeReviewCapability.REVIEW_CANDIDATE


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "KnowledgeReviewAction",
    "KnowledgeReviewActionEvent",
    "KnowledgeReviewActionId",
    "KnowledgeReviewCapability",
    "KnowledgeReviewCommand",
    "KnowledgeReviewItem",
    "KnowledgeReviewItemId",
    "KnowledgeReviewPolicyDecision",
    "KnowledgeReviewPolicyDecisionStatus",
    "KnowledgeReviewStatus",
    "KnowledgeReviewTargetKind",
    "KnowledgeReviewTargetRef",
    "PolicyApprovalEventReference",
    "ReviewDiffReference",
    "ReviewIdempotencyKey",
    "ReviewImpactReference",
    "ReviewPolicyTraceReference",
    "knowledge_review_action_event_id",
    "knowledge_review_command_fingerprint",
    "knowledge_review_target_hash",
    "knowledge_review_target_ref",
    "review_item_id",
]
