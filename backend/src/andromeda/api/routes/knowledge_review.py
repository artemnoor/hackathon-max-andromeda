from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from andromeda.api.dependencies.composition import get_composition_root
from andromeda.api.dependencies.knowledge_review import (
    get_knowledge_review_workflow,
    get_policy_approval_review_adapter,
    require_knowledge_review_access,
)
from andromeda.api.dependencies.request_context import get_session
from andromeda.api.schemas.knowledge_review import (
    ReviewActionHistoryResponse,
    ReviewConflictParticipantResponse,
    ReviewConflictResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewDiffEntryResponse,
    ReviewEvidenceResponse,
    ReviewPolicyPreviewContext,
    ReviewPolicyPreviewRequest,
    ReviewPolicyPreviewResponse,
    ReviewQueueItemResponse,
    ReviewQueueResponse,
    ReviewTargetResponse,
)
from andromeda.composition import AndromedaContainer
from andromeda.modules.auth.contracts.public import Account
from andromeda.modules.knowledge.contracts.public import (
    ChangeEvent,
    Claim,
    ClaimReviewState,
    ConflictParticipantKind,
    ConflictParticipantReference,
    EvidenceRef,
)
from andromeda.modules.knowledge.contracts.review import (
    KnowledgeReviewAction,
    KnowledgeReviewActionEvent,
    KnowledgeReviewCommand,
    KnowledgeReviewPolicyDecision,
    KnowledgeReviewTargetKind,
    KnowledgeReviewTargetRef,
    knowledge_review_target_ref,
)
from andromeda.modules.knowledge.repository.ports import (
    ConflictGroupRepository,
    KnowledgeCandidateRepository,
    KnowledgeReviewActionRepository,
    KnowledgeSourceRepository,
)
from andromeda.modules.knowledge.services.review_workflow import KnowledgeReviewWorkflow
from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalState,
)
from andromeda.modules.policy.contracts.resolution import PolicyResolutionRequest
from andromeda.modules.policy.contracts.rule import PolicyRuleRevision
from andromeda.modules.policy.contracts.semantic_diff import DiffObjectState
from andromeda.modules.policy.contracts.what_if import PolicyHypotheticalPreview
from andromeda.modules.policy.domain.approval import derive_approval_state
from andromeda.modules.policy.repository.ports import PolicyRuleRepository
from andromeda.modules.policy.services.knowledge_review_adapter import (
    PolicyApprovalReviewAdapter,
)
from andromeda.modules.policy.services.semantic_diff import build_policy_revision_diff
from andromeda.shared.contracts.errors import ConflictError

router = APIRouter(tags=["knowledge-review"])


@router.get(
    "/ops/knowledge/review-queue",
    response_model=ReviewQueueResponse,
    operation_id="list_knowledge_review_queue",
)
def list_knowledge_review_queue(
    _actor: Annotated[Account, Depends(require_knowledge_review_access)],
    container: Annotated[AndromedaContainer, Depends(get_composition_root)],
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ReviewQueueResponse:
    candidates = container.knowledge_candidate_repository(session)
    sources = container.knowledge_source_repository(session)
    policy_rules = container.policy_rule_repository(session)
    review_actions = container.knowledge_review_action_repository(session)
    conflict_groups = container.knowledge_conflict_repository(session)
    evidence_cache: dict[tuple[str, str], tuple[str | None, str | None]] = {}

    items = [
        _claim_item(item, sources, review_actions, conflict_groups, evidence_cache)
        for item in candidates.list_pending_claims(limit=limit)
    ]
    items.extend(
        _change_event_item(
            item, candidates, sources, review_actions, conflict_groups, evidence_cache
        )
        for item in candidates.list_pending_change_events(limit=limit)
    )
    items.extend(
        _policy_item(item, policy_rules, sources, conflict_groups, evidence_cache)
        for item in policy_rules.list_pending_revisions(limit=limit)
    )
    items.sort(key=lambda item: (item.created_at, item.target.object_id), reverse=True)
    return ReviewQueueResponse(items=tuple(items[:limit]), truncated=len(items) > limit)


@router.post(
    "/ops/knowledge/review-preview",
    response_model=ReviewPolicyPreviewResponse,
    operation_id="preview_knowledge_policy_review",
)
def preview_knowledge_policy_review(
    body: ReviewPolicyPreviewRequest,
    _actor: Annotated[Account, Depends(require_knowledge_review_access)],
    container: Annotated[AndromedaContainer, Depends(get_composition_root)],
    session: Annotated[Session, Depends(get_session)],
) -> ReviewPolicyPreviewResponse:
    target = _target_contract(body.target)
    if target.kind is not KnowledgeReviewTargetKind.POLICY_RULE:
        raise ConflictError("Hypothetical policy preview requires an exact policy-rule target")
    preview = container.policy_hypothetical_sandbox(session).preview(
        _resolution_request(body.context),
        rule_id=target.object_id,
        revision=target.revision,
        revision_hash=target.revision_hash,
    )
    return ReviewPolicyPreviewResponse(preview=preview)


@router.post(
    "/ops/knowledge/review-actions",
    response_model=ReviewDecisionResponse,
    status_code=status.HTTP_200_OK,
    operation_id="apply_knowledge_review_action",
)
def apply_knowledge_review_action(
    body: ReviewDecisionRequest,
    actor: Annotated[Account, Depends(require_knowledge_review_access)],
    container: Annotated[AndromedaContainer, Depends(get_composition_root)],
    session: Annotated[Session, Depends(get_session)],
    workflow: Annotated[
        KnowledgeReviewWorkflow, Depends(get_knowledge_review_workflow)
    ],
    policy_approval: Annotated[
        PolicyApprovalReviewAdapter, Depends(get_policy_approval_review_adapter)
    ],
) -> ReviewDecisionResponse:
    target = _target_contract(body.target)
    edited_claim: Claim | None = None
    preview_fingerprint: str | None = None
    review_preview: PolicyHypotheticalPreview | None = None
    if target.kind is KnowledgeReviewTargetKind.POLICY_RULE:
        if body.action not in {KnowledgeReviewAction.APPROVE, KnowledgeReviewAction.REJECT}:
            raise ConflictError("Policy review supports only policy-owned approve/reject actions")
        preview_context = body.policy_preview_context
        if preview_context is None or body.policy_preview_fingerprint is None:
            raise ConflictError("Policy review action requires an exact reviewer preview")
        preview = container.policy_hypothetical_sandbox(session).preview(
            _resolution_request(preview_context),
            rule_id=target.object_id,
            revision=target.revision,
            revision_hash=target.revision_hash,
        )
        review_preview = preview
        preview_fingerprint = body.policy_preview_fingerprint
    elif body.policy_preview_context is not None or body.policy_preview_fingerprint is not None:
        raise ConflictError("Policy preview details apply only to policy-rule review actions")

    if body.action in {KnowledgeReviewAction.EDIT, KnowledgeReviewAction.RESOLVE_IDENTITY}:
        if target.kind is not KnowledgeReviewTargetKind.CLAIM:
            raise ConflictError("This review action requires an exact source claim target")
        claim = container.knowledge_candidate_repository(session).get_claim_revision(
            target.object_id, target.revision
        )
        if claim is None or knowledge_review_target_ref(claim) != target:
            raise ConflictError("Claim revision is stale; reload the review queue")
        if claim.proposition is None:
            raise ConflictError("An untyped claim cannot be edited or identity-resolved")
        if body.action is KnowledgeReviewAction.EDIT:
            if body.edited_proposition is None or body.canonical_subject_id is not None:
                raise ConflictError("Claim edit requires exactly one typed replacement proposition")
            proposition = body.edited_proposition.to_contract()
        else:
            if body.canonical_subject_id is None or body.edited_proposition is not None:
                raise ConflictError("Identity resolution requires one exact canonical subject ID")
            proposition = claim.proposition.model_copy(
                update={"subject_id": body.canonical_subject_id}
            )
        recorded_at = datetime.now(UTC)
        edited_claim = claim.model_copy(
            update={
                "proposition": proposition,
                "clock": claim.clock.model_copy(
                    update={"revision": claim.clock.revision + 1, "recorded_at": recorded_at}
                ),
                "review_state": ClaimReviewState.NEEDS_REVIEW,
            }
        )
    elif body.edited_proposition is not None or body.canonical_subject_id is not None:
        raise ConflictError("Claim edit details apply only to edit or identity-resolution actions")

    if (
        body.action is KnowledgeReviewAction.APPROVE
        and target.kind is not KnowledgeReviewTargetKind.POLICY_RULE
    ):
        unresolved = container.knowledge_conflict_repository(
            session
        ).list_for_participant(_conflict_participant(target), limit=100)
        if len(unresolved) > 100 or any(
            group.state.value == "open" for group in unresolved
        ):
            raise ConflictError(
                "Source assertion review is blocked by an unresolved conflict"
            )
    command = KnowledgeReviewCommand(
        target=target,
        action=body.action,
        actor_account_id=actor.account_id,
        reason=body.reason,
        idempotency_key=body.idempotency_key,
        recorded_at=datetime.now(UTC),
        policy_preview_fingerprint=preview_fingerprint,
        edited_claim=edited_claim,
        related_target=_target_contract(body.related_target)
        if body.related_target
        else None,
    )
    event = (
        policy_approval.decide(command, review_preview=review_preview)
        if target.kind is KnowledgeReviewTargetKind.POLICY_RULE
        else workflow.apply(command)
    )
    if isinstance(event, KnowledgeReviewPolicyDecision):
        return ReviewDecisionResponse(
            event_id=event.approval_event_id,
            target=_target_response(event.target),
            action=event.action,
            status=event.status.value,
            actor_account_id=event.actor_account_id,
            reason=event.reason,
            recorded_at=event.recorded_at,
            result_revision=event.target.revision,
            result_hash=event.target.revision_hash,
            policy_preview_fingerprint=event.preview_fingerprint,
        )
    if not isinstance(event, KnowledgeReviewActionEvent):
        raise ConflictError(
            "Knowledge review returned an unsupported policy decision receipt"
        )
    return ReviewDecisionResponse(
        event_id=event.event_id,
        target=_target_response(event.target),
        action=event.action,
        status=event.action.value,
        actor_account_id=event.actor_account_id,
        reason=event.reason,
        recorded_at=event.recorded_at,
        result_revision=event.result.revision,
        result_hash=event.result.revision_hash,
    )


def _resolution_request(context: ReviewPolicyPreviewContext) -> PolicyResolutionRequest:
    return PolicyResolutionRequest(
        university_id=context.university_id,
        admission_year=context.admission_year,
        context=context.applicability,
        valid_as_of=context.valid_as_of,
    )


def _claim_item(
    claim: Claim,
    sources: KnowledgeSourceRepository,
    actions: KnowledgeReviewActionRepository,
    conflict_groups: ConflictGroupRepository,
    cache: dict[tuple[str, str], tuple[str | None, str | None]],
) -> ReviewQueueItemResponse:
    target = knowledge_review_target_ref(claim)
    evidence = tuple(
        _evidence_response(link.evidence, sources, cache) for link in claim.evidence
    )
    conflicts, conflicts_truncated = _conflict_data(
        target, conflict_groups, sources, cache
    )
    return ReviewQueueItemResponse(
        target=_target_response(target),
        review_state=claim.review_state.value,
        created_at=claim.clock.recorded_at,
        title=claim.proposition.predicate
        if claim.proposition
        else "Утверждение из источника",
        assertion_text=claim.assertion_text,
        proposition=claim.proposition,
        extraction_method=claim.extraction_method.value,
        extractor=f"{claim.extractor_id} {claim.extractor_version}",
        confidence=claim.extraction_confidence,
        claimed_stage=claim.claimed_stage.value,
        canonical_summary="Claim review confirms a source assertion only; it does not create a canonical policy or domain fact.",
        effective_from=(
            claim.source_milestones.effective_time.start
            if claim.source_milestones.effective_time
            else None
        ),
        evidence=evidence,
        impact_status="not_required",
        conflicts=conflicts,
        conflicts_truncated=conflicts_truncated,
        action_history=_knowledge_action_history(actions, target),
    )


def _change_event_item(
    event: ChangeEvent,
    candidates: KnowledgeCandidateRepository,
    sources: KnowledgeSourceRepository,
    actions: KnowledgeReviewActionRepository,
    conflict_groups: ConflictGroupRepository,
    cache: dict[tuple[str, str], tuple[str | None, str | None]],
) -> ReviewQueueItemResponse:
    target = knowledge_review_target_ref(event)
    conflicts, conflicts_truncated = _conflict_data(
        target, conflict_groups, sources, cache
    )
    return ReviewQueueItemResponse(
        target=_target_response(target),
        review_state=event.review_state.value,
        created_at=event.clock.recorded_at,
        title=event.event_kind.value.replace("_", " ").capitalize(),
        change_event_kind=event.event_kind.value,
        linked_claim_ids=tuple(item.claim_id for item in event.claims),
        related_assertions=tuple(
            claim.assertion_text
            for reference in event.claims
            if (
                claim := candidates.get_claim_revision(
                    reference.claim_id, reference.revision
                )
            )
            is not None
        ),
        effective_from=(
            event.source_milestones.effective_time.start
            if event.source_milestones.effective_time
            else None
        ),
        canonical_summary="Change-event review confirms a source-backed event only; it does not activate a rule.",
        evidence=tuple(
            _evidence_response(item, sources, cache) for item in event.evidence
        ),
        impact_status="not_required",
        conflicts=conflicts,
        conflicts_truncated=conflicts_truncated,
        action_history=_knowledge_action_history(actions, target),
    )


def _policy_item(
    revision: PolicyRuleRevision,
    rules: PolicyRuleRepository,
    sources: KnowledgeSourceRepository,
    conflict_groups: ConflictGroupRepository,
    cache: dict[tuple[str, str], tuple[str | None, str | None]],
) -> ReviewQueueItemResponse:
    target = KnowledgeReviewTargetRef(
        kind=KnowledgeReviewTargetKind.POLICY_RULE,
        object_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
    )
    before = (
        rules.get_revision(revision.rule_id, revision.revision - 1)
        if revision.revision > 1
        else None
    )
    events = rules.list_approval_events(revision.rule_id, revision.revision)
    approval = derive_approval_state(
        events,
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
    )
    before_approval = PolicyApprovalState.NOT_SUBMITTED
    if before is not None:
        before_events = rules.list_approval_events(before.rule_id, before.revision)
        before_approval = derive_approval_state(
            before_events,
            rule_id=before.rule_id,
            revision=before.revision,
            revision_hash=before.content_hash,
        )
    diff = build_policy_revision_diff(
        before=before,
        after=revision,
        before_state=(
            DiffObjectState.ABSENT_CONFIRMED
            if before is None and revision.revision == 1
            else None
        ),
        after_state=DiffObjectState.PRESENT,
        after_approval=approval,
        before_approval=before_approval,
    )
    scope = revision.scope.level.value
    if revision.scope.scope_id is not None:
        scope = f"{scope}: {revision.scope.scope_id}"
    conflicts, conflicts_truncated = _conflict_data(
        target, conflict_groups, sources, cache
    )
    return ReviewQueueItemResponse(
        target=_target_response(target),
        review_state=approval.value,
        created_at=revision.temporal.clock.recorded_at,
        title=revision.domain_rule.canonical_rule_id,
        policy_lifecycle=revision.lifecycle.value,
        policy_authority=revision.authority.value if revision.authority else None,
        policy_scope=scope,
        domain_rule_id=revision.domain_rule.canonical_rule_id,
        canonical_summary=(
            f"Previous exact policy revision: {before.revision}."
            if before is not None
            else "No immediately preceding revision was found; this does not establish that no related policy exists."
        ),
        effective_from=revision.temporal.source_milestones.effective_time.start
        if revision.temporal.source_milestones.effective_time
        else None,
        evidence=tuple(
            _evidence_response(item, sources, cache) for item in revision.evidence
        ),
        diff=tuple(
            ReviewDiffEntryResponse(
                path=item.path,
                kind=item.kind.value,
                before=item.before,
                after=item.after,
                reason_code=item.reason_code,
            )
            for item in diff.changes
        ),
        impact_status="unavailable",
        impact_reason="policy_review_preview_endpoint_not_composed",
        conflicts=conflicts,
        conflicts_truncated=conflicts_truncated,
        action_history=tuple(
            ReviewActionHistoryResponse(
                action=item.kind.value,
                actor_account_id=item.actor_account_id,
                reason=item.reason,
                recorded_at=item.recorded_at,
                result_revision=item.revision,
                result_hash=item.revision_hash,
                policy_preview_fingerprint=item.preview_fingerprint,
            )
            for item in events
        ),
    )


def _evidence_response(
    evidence: EvidenceRef,
    sources: KnowledgeSourceRepository,
    cache: dict[tuple[str, str], tuple[str | None, str | None]],
) -> ReviewEvidenceResponse:
    key = (evidence.source_id, evidence.source_observation_id)
    source_name, reliability = cache.get(key, (None, None))
    if key not in cache:
        observation = sources.get_observation(evidence.source_observation_id)
        if observation is not None:
            identity = sources.get_source_identity(observation.source_id)
            registry = sources.get_registry_revision(
                observation.source_id, observation.registry_revision
            )
            source_name = identity.display_name if identity else None
            reliability = registry.reliability_tier.value if registry else None
        cache[key] = (source_name, reliability)
    locator = evidence.locator
    return ReviewEvidenceResponse(
        source_id=evidence.source_id,
        source_observation_id=evidence.source_observation_id,
        snapshot_sha256=evidence.snapshot_sha256,
        source_name=source_name,
        reliability_tier=reliability,
        source_url=str(evidence.source_url),
        page=locator.page,
        table=locator.table,
        row=locator.row,
        section=locator.section,
        field=locator.field,
        record_key=locator.record_key,
        inferred=evidence.inferred,
    )


def _conflict_participant(
    target: KnowledgeReviewTargetRef,
) -> ConflictParticipantReference:
    kind = {
        KnowledgeReviewTargetKind.CLAIM: ConflictParticipantKind.CLAIM_REVISION,
        KnowledgeReviewTargetKind.CHANGE_EVENT: ConflictParticipantKind.CHANGE_EVENT_REVISION,
        KnowledgeReviewTargetKind.POLICY_RULE: ConflictParticipantKind.POLICY_RULE_REVISION,
    }[target.kind]
    content_hash = (
        target.revision_hash
        if kind
        in {
            ConflictParticipantKind.CLAIM_REVISION,
            ConflictParticipantKind.POLICY_RULE_REVISION,
        }
        else None
    )
    return ConflictParticipantReference(
        kind=kind,
        object_id=target.object_id,
        revision=target.revision,
        content_hash=content_hash,
    )


def _conflict_data(
    target: KnowledgeReviewTargetRef,
    conflicts: ConflictGroupRepository,
    sources: KnowledgeSourceRepository,
    cache: dict[tuple[str, str], tuple[str | None, str | None]],
) -> tuple[tuple[ReviewConflictResponse, ...], bool]:
    groups = conflicts.list_for_participant(_conflict_participant(target), limit=20)
    responses = tuple(
        ReviewConflictResponse(
            conflict_id=group.revision.conflict_id,
            kind=group.revision.kind.value,
            state=group.state.value,
            scope=(
                f"{group.revision.scope.level.value}: {group.revision.scope.scope_id}"
                if group.revision.scope
                else None
            ),
            participants=tuple(
                ReviewConflictParticipantResponse(
                    kind=participant.reference.kind.value,
                    object_id=participant.reference.object_id,
                    revision=participant.reference.revision,
                    content_hash=participant.reference.content_hash,
                    role=participant.role.value,
                    evidence=tuple(
                        _evidence_response(evidence, sources, cache)
                        for evidence in participant.evidence
                    ),
                )
                for participant in group.revision.participants
            ),
        )
        for group in groups[:20]
    )
    return responses, len(groups) > 20


def _knowledge_action_history(
    actions: KnowledgeReviewActionRepository,
    target: KnowledgeReviewTargetRef,
) -> tuple[ReviewActionHistoryResponse, ...]:
    return tuple(
        ReviewActionHistoryResponse(
            action=item.action.value,
            actor_account_id=item.actor_account_id,
            reason=item.reason,
            recorded_at=item.recorded_at,
            result_revision=item.result.revision,
            result_hash=item.result.revision_hash,
        )
        for item in actions.list_actions(target, limit=100)
    )


def _target_contract(target: ReviewTargetResponse) -> KnowledgeReviewTargetRef:
    return KnowledgeReviewTargetRef(
        kind=target.kind,
        object_id=target.object_id,
        revision=target.revision,
        revision_hash=target.revision_hash,
    )


def _target_response(target: KnowledgeReviewTargetRef) -> ReviewTargetResponse:
    return ReviewTargetResponse(
        kind=target.kind,
        object_id=target.object_id,
        revision=target.revision,
        revision_hash=target.revision_hash,
    )


__all__ = ["router"]
