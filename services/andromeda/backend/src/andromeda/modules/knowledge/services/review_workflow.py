"""Capability-gated review transitions for immutable claim/event candidates."""

from __future__ import annotations

import logging
from typing import Protocol

from andromeda.modules.knowledge.contracts.public import (
    ChangeEvent,
    ChangeEventReviewState,
    Claim,
    ClaimReviewState,
    KnowledgeReviewPolicyDecision,
)
from andromeda.modules.knowledge.contracts.review import (
    KnowledgeReviewAction,
    KnowledgeReviewActionEvent,
    KnowledgeReviewCapability,
    KnowledgeReviewCommand,
    KnowledgeReviewTargetKind,
    KnowledgeReviewTargetRef,
    knowledge_review_action_event_id,
    knowledge_review_command_fingerprint,
    knowledge_review_target_ref,
)
from andromeda.modules.knowledge.domain.change_event import (
    transition_change_event_review,
)
from andromeda.modules.knowledge.domain.claim import transition_claim_review
from andromeda.modules.knowledge.repository.ports import (
    KnowledgeReviewActionRepository,
    KnowledgeReviewAuthorizer,
    KnowledgeReviewCandidateRepository,
    KnowledgeReviewUnitOfWork,
)
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger("andromeda.modules.knowledge.review_workflow")


class KnowledgeReviewPolicyApprovalPort(Protocol):
    """Delegates exact policy decisions to the policy-owned approval ledger."""

    def decide(self, command: KnowledgeReviewCommand) -> KnowledgeReviewPolicyDecision: ...


class KnowledgeReviewIdentityResolver(Protocol):
    """Confirms a proposed human identity against an existing canonical registry."""

    def require_exact_identity(self, canonical_id: str, *, claim: Claim) -> None: ...


class KnowledgeReviewWorkflow:
    """Review source claims and change events without owning policy approval."""

    def __init__(
        self,
        *,
        candidates: KnowledgeReviewCandidateRepository,
        actions: KnowledgeReviewActionRepository,
        authorizer: KnowledgeReviewAuthorizer,
        unit_of_work: KnowledgeReviewUnitOfWork,
        identity_resolver: KnowledgeReviewIdentityResolver | None = None,
        policy_approval_port: KnowledgeReviewPolicyApprovalPort | None = None,
    ) -> None:
        self._candidates = candidates
        self._actions = actions
        self._authorizer = authorizer
        self._unit_of_work = unit_of_work
        self._identity_resolver = identity_resolver
        self._policy_approval_port = policy_approval_port

    def apply(
        self, command: KnowledgeReviewCommand
    ) -> KnowledgeReviewActionEvent | KnowledgeReviewPolicyDecision:
        if command.target.kind is KnowledgeReviewTargetKind.POLICY_RULE:
            return self._delegate_policy_decision(command)
        capability = _required_capability(command.action)
        self._authorizer.require_capability(
            command.actor_account_id,
            capability,
            command.target,
        )
        fingerprint = knowledge_review_command_fingerprint(command)
        existing = self._actions.get_action_by_idempotency_key(
            command.actor_account_id,
            command.idempotency_key,
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ConflictError("Review idempotency key was already used for another command")
            return existing

        try:
            current = self._get_candidate(command)
            if knowledge_review_target_ref(current) != command.target:
                raise ConflictError("Review candidate revision is stale or its hash changed")
            related = self._get_related_candidate(command)
            result = self._apply_owner_transition(command, current)
            result_ref = knowledge_review_target_ref(result)
            event = KnowledgeReviewActionEvent(
                event_id=knowledge_review_action_event_id(
                    idempotency_key=command.idempotency_key,
                    request_fingerprint=fingerprint,
                    target=command.target,
                    action=command.action,
                    result=result_ref,
                    related_target=related,
                    actor_account_id=command.actor_account_id,
                    capability=capability,
                    reason=command.reason,
                    recorded_at=command.recorded_at,
                ),
                idempotency_key=command.idempotency_key,
                request_fingerprint=fingerprint,
                target=command.target,
                action=command.action,
                result=result_ref,
                related_target=related,
                actor_account_id=command.actor_account_id,
                capability=capability,
                reason=command.reason,
                recorded_at=command.recorded_at,
            )
            appended = self._actions.append_action(event)
            if appended != event:
                raise ConflictError("Review action persistence returned a different immutable event")
            self._unit_of_work.commit()
            logger.info(
                "knowledge_review_action_recorded event_id=%s kind=%s target_id=%s action=%s",
                event.event_id,
                command.target.kind.value,
                command.target.object_id,
                command.action.value,
            )
            return event
        except ConflictError as exc:
            self._unit_of_work.rollback()
            existing = self._actions.get_action_by_idempotency_key(
                command.actor_account_id,
                command.idempotency_key,
            )
            if existing is not None:
                if existing.request_fingerprint == fingerprint:
                    return existing
                raise ConflictError(
                    "Review idempotency key was concurrently used for another action"
                ) from exc
            raise
        except Exception:
            self._unit_of_work.rollback()
            raise

    def _delegate_policy_decision(
        self, command: KnowledgeReviewCommand
    ) -> KnowledgeReviewPolicyDecision:
        if self._policy_approval_port is None:
            raise ValidationError("policy-owned approval command is not configured")
        decision = self._policy_approval_port.decide(command)
        if (
            decision.target != command.target
            or decision.action is not command.action
            or decision.actor_account_id != command.actor_account_id
            or decision.reason != command.reason
            or decision.recorded_at != command.recorded_at
            or decision.preview_fingerprint != command.policy_preview_fingerprint
        ):
            raise ConflictError("Policy approval port returned a decision for a different command")
        return decision

    def _get_candidate(self, command: KnowledgeReviewCommand) -> Claim | ChangeEvent:
        target = command.target
        candidate: Claim | ChangeEvent | None
        if target.kind is KnowledgeReviewTargetKind.CLAIM:
            candidate = self._candidates.get_claim_revision(target.object_id, target.revision)
        elif target.kind is KnowledgeReviewTargetKind.CHANGE_EVENT:
            candidate = self._candidates.get_change_event_revision(target.object_id, target.revision)
        else:
            raise ValidationError("policy revisions must use the policy-owned approval command")
        if candidate is None:
            raise NotFoundError("Exact knowledge review candidate does not exist")
        return candidate

    def _get_related_candidate(
        self, command: KnowledgeReviewCommand
    ) -> KnowledgeReviewTargetRef | None:
        reference = command.related_target
        if reference is None:
            return None
        candidate: Claim | ChangeEvent | None
        if reference.kind is KnowledgeReviewTargetKind.CLAIM:
            candidate = self._candidates.get_claim_revision(reference.object_id, reference.revision)
        elif reference.kind is KnowledgeReviewTargetKind.CHANGE_EVENT:
            candidate = self._candidates.get_change_event_revision(
                reference.object_id,
                reference.revision,
            )
        else:
            raise ValidationError("merge target must be a knowledge-owned candidate")
        if candidate is None or knowledge_review_target_ref(candidate) != reference:
            raise ConflictError("Related review target is missing or stale")
        return reference

    def _apply_owner_transition(
        self,
        command: KnowledgeReviewCommand,
        current: Claim | ChangeEvent,
    ) -> Claim | ChangeEvent:
        if command.recorded_at <= current.clock.recorded_at:
            raise ValidationError("review action must follow the exact candidate system time")
        if command.action in {KnowledgeReviewAction.EDIT, KnowledgeReviewAction.RESOLVE_IDENTITY}:
            return self._append_edited_candidate(command, current)
        if command.action in {
            KnowledgeReviewAction.MERGE,
            KnowledgeReviewAction.MARK_DUPLICATE,
        } and command.related_target is None:
            raise ValidationError("duplicate review action requires an exact related candidate")
        if isinstance(current, Claim):
            target_state = _claim_target_state(command.action)
            try:
                transition_claim_review(current.review_state, target_state)
            except ValueError as exc:
                raise ConflictError("Claim review transition is not allowed from its current state") from exc
            revision = current.model_copy(
                update={
                    "clock": current.clock.model_copy(
                        update={
                            "revision": current.clock.revision + 1,
                            "recorded_at": command.recorded_at,
                        }
                    ),
                    "review_state": target_state,
                }
            )
            return self._candidates.append_reviewed_claim_revision(revision)
        event_target_state = _event_target_state(command.action)
        try:
            transition_change_event_review(current.review_state, event_target_state)
        except ValueError as exc:
            raise ConflictError("Change-event review transition is not allowed from its current state") from exc
        event_revision = current.model_copy(
            update={
                "clock": current.clock.model_copy(
                    update={
                        "revision": current.clock.revision + 1,
                        "recorded_at": command.recorded_at,
                    }
                ),
                "review_state": event_target_state,
            }
        )
        return self._candidates.append_reviewed_change_event_revision(event_revision)

    def _append_edited_candidate(
        self,
        command: KnowledgeReviewCommand,
        current: Claim | ChangeEvent,
    ) -> Claim | ChangeEvent:
        editable = (
            current.review_state
            in {ClaimReviewState.NEEDS_REVIEW, ClaimReviewState.UNRESOLVED}
            if isinstance(current, Claim)
            else current.review_state
            in {ChangeEventReviewState.NEEDS_REVIEW, ChangeEventReviewState.UNRESOLVED}
        )
        if not editable:
            raise ConflictError("Only a pending or unresolved candidate can be edited")
        if isinstance(current, Claim):
            replacement = command.edited_claim
            if replacement is None:
                raise ValidationError("Claim edit payload is missing")
            _validate_claim_edit(current, replacement, command)
            if command.action is KnowledgeReviewAction.RESOLVE_IDENTITY:
                if self._identity_resolver is None or replacement.proposition is None:
                    raise ValidationError("canonical identity resolution port is unavailable")
                identity = replacement.proposition.subject_id
                if identity is None:
                    raise ValidationError("identity resolution requires an exact canonical subject ID")
                self._identity_resolver.require_exact_identity(identity, claim=current)
            return self._candidates.append_claim_candidate(replacement)
        replacement_event = command.edited_change_event
        if replacement_event is None:
            raise ValidationError("Change-event edit payload is missing")
        _validate_event_edit(current, replacement_event, command)
        return self._candidates.append_change_event_candidate(replacement_event)


def _required_capability(action: KnowledgeReviewAction) -> KnowledgeReviewCapability:
    if action is KnowledgeReviewAction.EDIT:
        return KnowledgeReviewCapability.EDIT_CANDIDATE
    if action is KnowledgeReviewAction.RESOLVE_IDENTITY:
        return KnowledgeReviewCapability.RESOLVE_IDENTITY
    return KnowledgeReviewCapability.REVIEW_CANDIDATE


def _claim_target_state(action: KnowledgeReviewAction) -> ClaimReviewState:
    return {
        KnowledgeReviewAction.APPROVE: ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION,
        KnowledgeReviewAction.REJECT: ClaimReviewState.REJECTED,
        KnowledgeReviewAction.MARK_UNRESOLVED: ClaimReviewState.UNRESOLVED,
        KnowledgeReviewAction.MERGE: ClaimReviewState.DUPLICATE,
        KnowledgeReviewAction.MARK_DUPLICATE: ClaimReviewState.DUPLICATE,
    }[action]


def _event_target_state(action: KnowledgeReviewAction) -> ChangeEventReviewState:
    return {
        KnowledgeReviewAction.APPROVE: ChangeEventReviewState.ACCEPTED_AS_SOURCE_EVENT,
        KnowledgeReviewAction.REJECT: ChangeEventReviewState.REJECTED,
        KnowledgeReviewAction.MARK_UNRESOLVED: ChangeEventReviewState.UNRESOLVED,
        KnowledgeReviewAction.MERGE: ChangeEventReviewState.DUPLICATE,
        KnowledgeReviewAction.MARK_DUPLICATE: ChangeEventReviewState.DUPLICATE,
    }[action]


def _validate_claim_edit(
    current: Claim,
    replacement: Claim,
    command: KnowledgeReviewCommand,
) -> None:
    if replacement.clock.recorded_at != command.recorded_at or replacement.clock.valid_time != current.clock.valid_time:
        raise ValidationError("edited claim must keep valid time and use the review action time")
    if (
        replacement.source_observation_id != current.source_observation_id
        or replacement.text_start_offset != current.text_start_offset
        or replacement.text_end_offset != current.text_end_offset
        or replacement.assertion_text != current.assertion_text
        or replacement.assertion_text_sha256 != current.assertion_text_sha256
        or replacement.source_milestones != current.source_milestones
        or replacement.extraction_method is not current.extraction_method
        or replacement.extractor_id != current.extractor_id
        or replacement.extractor_version != current.extractor_version
        or replacement.extraction_confidence != current.extraction_confidence
        or replacement.evidence != current.evidence
    ):
        raise ValidationError("claim edit cannot replace its source assertion or provenance")
    if command.action is KnowledgeReviewAction.RESOLVE_IDENTITY:
        if current.proposition is None or replacement.proposition is None:
            raise ValidationError("identity resolution requires an existing typed proposition")
        expected = current.proposition.model_copy(
            update={"subject_id": replacement.proposition.subject_id}
        )
        if expected != replacement.proposition:
            raise ValidationError("identity resolution may change only the canonical subject ID")
    elif command.action is KnowledgeReviewAction.EDIT:
        if current.proposition is None or replacement.proposition is None:
            raise ValidationError("claim edit requires an existing typed proposition")
        expected = current.proposition.model_copy(
            update={
                "predicate": replacement.proposition.predicate,
                "value": replacement.proposition.value,
                "unit": replacement.proposition.unit,
            }
        )
        if expected != replacement.proposition:
            raise ValidationError(
                "claim edit cannot change subject kind or canonical identity; use identity resolution"
            )


def _validate_event_edit(
    current: ChangeEvent,
    replacement: ChangeEvent,
    command: KnowledgeReviewCommand,
) -> None:
    if (
        replacement.clock.recorded_at != command.recorded_at
        or replacement.clock.valid_time != current.clock.valid_time
        or replacement.primary_source_observation_id != current.primary_source_observation_id
        or replacement.event_kind is not current.event_kind
        or replacement.claims != current.claims
        or replacement.evidence != current.evidence
    ):
        raise ValidationError(
            "change-event edit cannot replace its identity, claims, evidence, or valid time"
        )


__all__ = [
    "KnowledgeReviewIdentityResolver",
    "KnowledgeReviewPolicyApprovalPort",
    "KnowledgeReviewWorkflow",
]
