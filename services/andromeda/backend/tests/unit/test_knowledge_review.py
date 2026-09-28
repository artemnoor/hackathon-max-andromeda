from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    Claim,
    ClaimedPolicyStage,
    ClaimEvidenceLink,
    ClaimEvidenceRelationship,
    ClaimExtractionMethod,
    ClaimProposition,
    ClaimReviewState,
    ClaimSubjectKind,
    ClaimValueDecimal,
    EvidenceLocator,
    EvidenceRef,
    SourceMilestones,
    TemporalInterval,
    claim_id_for_source_assertion,
)
from andromeda.modules.knowledge.contracts.review import (
    KnowledgeReviewAction,
    KnowledgeReviewActionEvent,
    KnowledgeReviewCapability,
    KnowledgeReviewCommand,
    KnowledgeReviewPolicyDecision,
    KnowledgeReviewPolicyDecisionStatus,
    KnowledgeReviewTargetKind,
    KnowledgeReviewTargetRef,
    knowledge_review_target_ref,
)
from andromeda.modules.knowledge.services.review_workflow import KnowledgeReviewWorkflow
from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalCapability,
    PolicyApprovalCommand,
    PolicyApprovalEvent,
    PolicyApprovalEventKind,
    policy_approval_event_id,
)
from andromeda.modules.policy.services.knowledge_review_adapter import (
    PolicyApprovalReviewAdapter,
)
from andromeda.shared.contracts.errors import ConflictError
from andromeda.shared.contracts.errors import (
    ValidationError as AndromedaValidationError,
)

NOW = datetime(2027, 12, 15, 12, tzinfo=UTC)
CAPTURED = NOW - timedelta(hours=1)
ACTOR = "account:" + "a" * 32
SOURCE_ID = "source:ministry"
OBSERVATION_A = "source-observation:" + "1" * 32
OBSERVATION_B = "source-observation:" + "2" * 32
SNAPSHOT_HASH = "b" * 64
ASSERTION = "The ministry proposed a new admission rule."


def _claim(
    *,
    observation_id: str = OBSERVATION_A,
    revision: int = 1,
    recorded_at: datetime = NOW,
    review_state: ClaimReviewState = ClaimReviewState.NEEDS_REVIEW,
    subject_id: str | None = None,
) -> Claim:
    assertion_hash = hashlib.sha256(ASSERTION.encode("utf-8")).hexdigest()
    evidence = EvidenceRef(
        source_id=SOURCE_ID,
        source_observation_id=observation_id,
        snapshot_sha256=SNAPSHOT_HASH,
        source_url="https://official.example/admission/rules",
        locator=EvidenceLocator(section="Admission rules, section 4"),
    )
    return Claim(
        claim_id=claim_id_for_source_assertion(
            observation_id,
            0,
            len(ASSERTION),
            assertion_hash,
        ),
        clock=BitemporalRevision(
            revision=revision,
            valid_time=TemporalInterval(start=CAPTURED),
            recorded_at=recorded_at,
        ),
        source_observation_id=observation_id,
        text_start_offset=0,
        text_end_offset=len(ASSERTION),
        assertion_text=ASSERTION,
        assertion_text_sha256=assertion_hash,
        proposition=ClaimProposition(
            predicate="admission.minimum_score",
            subject_kind=ClaimSubjectKind.UNIVERSITY,
            subject_id=subject_id,
            value=ClaimValueDecimal(kind="decimal", value=Decimal(70)),
            unit="points",
        ),
        claimed_stage=ClaimedPolicyStage.PROPOSAL,
        review_state=review_state,
        source_milestones=SourceMilestones(
            announced_at=CAPTURED,
            captured_at=CAPTURED,
        ),
        extraction_method=ClaimExtractionMethod.JEV_SUGGESTION,
        extractor_id="jev-classifier",
        extractor_version="v1",
        extraction_confidence=Decimal("0.8700"),
        evidence=(
            ClaimEvidenceLink(
                relationship=ClaimEvidenceRelationship.ORIGINATES_FROM,
                evidence=evidence,
            ),
        ),
    )


def _command(
    target: KnowledgeReviewTargetRef,
    action: KnowledgeReviewAction,
    *,
    key_suffix: str = "c",
    recorded_at: datetime = NOW + timedelta(minutes=1),
    related_target: KnowledgeReviewTargetRef | None = None,
    edited_claim: Claim | None = None,
) -> KnowledgeReviewCommand:
    return KnowledgeReviewCommand(
        target=target,
        action=action,
        actor_account_id=ACTOR,
        reason="Reviewed against the captured source and exact evidence locator.",
        idempotency_key="review-idempotency:" + key_suffix * 64,
        recorded_at=recorded_at,
        related_target=related_target,
        edited_claim=edited_claim,
        policy_preview_fingerprint=(
            "a" * 64
            if target.kind is KnowledgeReviewTargetKind.POLICY_RULE
            and action is KnowledgeReviewAction.APPROVE
            else None
        ),
    )


class _Candidates:
    def __init__(self, *claims: Claim) -> None:
        self.claims = {
            (claim.claim_id, claim.clock.revision): claim
            for claim in claims
        }
        self.write_count = 0
        self.fail_write = False

    def get_claim_revision(self, claim_id: str, revision: int) -> Claim | None:
        return self.claims.get((claim_id, revision))

    def get_change_event_revision(self, event_id: str, revision: int) -> None:
        del event_id, revision

    def append_claim_candidate(self, claim: Claim) -> Claim:
        self.write_count += 1
        if self.fail_write:
            raise RuntimeError("simulated owner write failure")
        self.claims[(claim.claim_id, claim.clock.revision)] = claim
        return claim

    def append_reviewed_claim_revision(self, claim: Claim) -> Claim:
        self.write_count += 1
        if self.fail_write:
            raise RuntimeError("simulated owner write failure")
        self.claims[(claim.claim_id, claim.clock.revision)] = claim
        return claim

    def append_change_event_candidate(self, event: object) -> object:
        raise AssertionError("change-event action was not expected in this test")

    def append_reviewed_change_event_revision(self, event: object) -> object:
        raise AssertionError("change-event action was not expected in this test")


class _Actions:
    def __init__(self) -> None:
        self.by_actor_key: dict[tuple[str, str], KnowledgeReviewActionEvent] = {}
        self.append_count = 0

    def get_action_by_idempotency_key(
        self,
        actor_account_id: str,
        idempotency_key: str,
    ) -> KnowledgeReviewActionEvent | None:
        return self.by_actor_key.get((actor_account_id, idempotency_key))

    def append_action(self, event: KnowledgeReviewActionEvent) -> KnowledgeReviewActionEvent:
        self.append_count += 1
        self.by_actor_key[(event.actor_account_id, event.idempotency_key)] = event
        return event

    def list_actions(self, target: KnowledgeReviewTargetRef, *, limit: int = 100) -> tuple[()]:
        del target, limit
        return ()


class _Authorizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, KnowledgeReviewCapability, KnowledgeReviewTargetRef]] = []

    def require_capability(
        self,
        actor_account_id: str,
        capability: KnowledgeReviewCapability,
        target: KnowledgeReviewTargetRef,
    ) -> None:
        self.calls.append((actor_account_id, capability, target))


class _UnitOfWork:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class _IdentityResolver:
    def __init__(self, canonical_ids: set[str]) -> None:
        self.canonical_ids = canonical_ids
        self.resolved: list[str] = []

    def require_exact_identity(self, canonical_id: str, *, claim: Claim) -> None:
        del claim
        if canonical_id not in self.canonical_ids:
            raise ConflictError("Canonical identity is not in the allowed registry")
        self.resolved.append(canonical_id)


class _PolicyApprovalPort:
    def __init__(self) -> None:
        self.commands: list[KnowledgeReviewCommand] = []

    def decide(self, command: KnowledgeReviewCommand) -> KnowledgeReviewPolicyDecision:
        self.commands.append(command)
        status = (
            KnowledgeReviewPolicyDecisionStatus.APPROVED
            if command.action is KnowledgeReviewAction.APPROVE
            else KnowledgeReviewPolicyDecisionStatus.REJECTED
        )
        return KnowledgeReviewPolicyDecision(
            target=command.target,
            action=command.action,
            status=status,
            approval_event_id="policy-approval-event:" + "9" * 64,
            sequence=2,
            actor_account_id=command.actor_account_id,
            reason=command.reason,
            recorded_at=command.recorded_at,
            preview_fingerprint=command.policy_preview_fingerprint,
        )


class _PolicyApprovalCommands:
    def __init__(self) -> None:
        self.commands: list[PolicyApprovalCommand] = []
        self.review_previews: list[object] = []

    def decide(
        self,
        command: PolicyApprovalCommand,
        *,
        review_preview: object | None = None,
    ) -> PolicyApprovalEvent:
        self.commands.append(command)
        if review_preview is not None:
            self.review_previews.append(review_preview)
        return PolicyApprovalEvent(
            event_id=policy_approval_event_id(
                command.rule_id,
                command.revision,
                2,
                command.kind,
                command.revision_hash,
                preview_fingerprint=command.preview_fingerprint,
            ),
            rule_id=command.rule_id,
            revision=command.revision,
            sequence=2,
            revision_hash=command.revision_hash,
            kind=command.kind,
            actor_account_id=command.actor_account_id,
            capability=PolicyApprovalCapability.APPROVE_REVISION,
            reason=command.reason,
            recorded_at=command.recorded_at,
            preview_fingerprint=command.preview_fingerprint,
        )

def _workflow(
    claim: Claim,
    *,
    related_claim: Claim | None = None,
    identity_resolver: _IdentityResolver | None = None,
    policy_approval_port: _PolicyApprovalPort | None = None,
) -> tuple[KnowledgeReviewWorkflow, _Candidates, _Actions, _UnitOfWork, _Authorizer]:
    candidates = _Candidates(*(item for item in (claim, related_claim) if item is not None))
    actions = _Actions()
    unit_of_work = _UnitOfWork()
    authorizer = _Authorizer()
    workflow = KnowledgeReviewWorkflow(
        candidates=candidates,  # type: ignore[arg-type]
        actions=actions,  # type: ignore[arg-type]
        authorizer=authorizer,  # type: ignore[arg-type]
        unit_of_work=unit_of_work,
        identity_resolver=identity_resolver,
        policy_approval_port=policy_approval_port,  # type: ignore[arg-type]
    )
    return workflow, candidates, actions, unit_of_work, authorizer


def test_review_approval_appends_exact_revision_and_replay_is_idempotent() -> None:
    current = _claim()
    workflow, candidates, actions, unit_of_work, authorizer = _workflow(current)
    command = _command(
        knowledge_review_target_ref(current),
        KnowledgeReviewAction.APPROVE,
    )

    first = workflow.apply(command)
    replay = workflow.apply(command)

    assert first == replay
    assert first.result.revision == 2
    assert candidates.get_claim_revision(current.claim_id, 2).review_state is (
        ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION
    )
    assert candidates.write_count == 1
    assert actions.append_count == 1
    assert unit_of_work.commit_count == 1
    assert unit_of_work.rollback_count == 0
    assert len(authorizer.calls) == 2
    assert authorizer.calls[0][1] is KnowledgeReviewCapability.REVIEW_CANDIDATE


def test_reused_idempotency_key_with_different_command_conflicts() -> None:
    current = _claim()
    workflow, _, _, unit_of_work, _ = _workflow(current)
    command = _command(knowledge_review_target_ref(current), KnowledgeReviewAction.APPROVE)
    workflow.apply(command)
    changed = command.model_copy(update={"reason": "A different decision reason."})

    with pytest.raises(ConflictError, match="already used"):
        workflow.apply(changed)

    assert unit_of_work.commit_count == 1
    assert unit_of_work.rollback_count == 0


def test_stale_revision_hash_fails_closed_and_rolls_back() -> None:
    current = _claim()
    stale = knowledge_review_target_ref(current).model_copy(update={"revision_hash": "d" * 64})
    workflow, candidates, actions, unit_of_work, _ = _workflow(current)

    with pytest.raises(ConflictError, match="stale"):
        workflow.apply(_command(stale, KnowledgeReviewAction.APPROVE))

    assert candidates.write_count == 0
    assert actions.append_count == 0
    assert unit_of_work.commit_count == 0
    assert unit_of_work.rollback_count == 1


def test_duplicate_decision_requires_and_records_exact_related_candidate() -> None:
    current = _claim()
    related = _claim(observation_id=OBSERVATION_B)
    workflow, candidates, _, unit_of_work, _ = _workflow(current, related_claim=related)
    related_ref = knowledge_review_target_ref(related)

    event = workflow.apply(
        _command(
            knowledge_review_target_ref(current),
            KnowledgeReviewAction.MARK_DUPLICATE,
            related_target=related_ref,
        )
    )

    assert event.related_target == related_ref
    assert candidates.get_claim_revision(current.claim_id, 2).review_state is ClaimReviewState.DUPLICATE
    assert unit_of_work.commit_count == 1


def test_identity_resolution_changes_only_exact_canonical_subject() -> None:
    current = _claim(subject_id=None)
    identity = "university:bmstu"
    replacement = current.model_copy(
        update={
            "clock": current.clock.model_copy(
                update={"revision": 2, "recorded_at": NOW + timedelta(minutes=1)}
            ),
            "proposition": current.proposition.model_copy(update={"subject_id": identity}),
            "review_state": ClaimReviewState.NEEDS_REVIEW,
        }
    )
    identity_resolver = _IdentityResolver({identity})
    workflow, candidates, _, unit_of_work, authorizer = _workflow(
        current,
        identity_resolver=identity_resolver,
    )

    event = workflow.apply(
        _command(
            knowledge_review_target_ref(current),
            KnowledgeReviewAction.RESOLVE_IDENTITY,
            edited_claim=replacement,
        )
    )

    assert event.capability is KnowledgeReviewCapability.RESOLVE_IDENTITY
    assert candidates.get_claim_revision(current.claim_id, 2).proposition.subject_id == identity
    assert identity_resolver.resolved == [identity]
    assert authorizer.calls[0][1] is KnowledgeReviewCapability.RESOLVE_IDENTITY
    assert unit_of_work.commit_count == 1


def test_generic_claim_edit_cannot_bypass_exact_identity_resolution() -> None:
    current = _claim(subject_id=None)
    replacement = current.model_copy(
        update={
            "clock": current.clock.model_copy(
                update={"revision": 2, "recorded_at": NOW + timedelta(minutes=1)}
            ),
            "proposition": current.proposition.model_copy(
                update={"subject_id": "university:invented"}
            ),
            "review_state": ClaimReviewState.NEEDS_REVIEW,
        }
    )
    workflow, candidates, actions, unit_of_work, _ = _workflow(current)

    with pytest.raises(AndromedaValidationError, match="use identity resolution"):
        workflow.apply(
            _command(
                knowledge_review_target_ref(current),
                KnowledgeReviewAction.EDIT,
                edited_claim=replacement,
            )
        )

    assert candidates.write_count == 0
    assert actions.append_count == 0
    assert unit_of_work.rollback_count == 1


def test_owner_write_failure_rolls_back_without_audit_action() -> None:
    current = _claim()
    workflow, candidates, actions, unit_of_work, _ = _workflow(current)
    candidates.fail_write = True

    with pytest.raises(RuntimeError, match="owner write failure"):
        workflow.apply(
            _command(knowledge_review_target_ref(current), KnowledgeReviewAction.APPROVE)
        )

    assert actions.append_count == 0
    assert unit_of_work.commit_count == 0
    assert unit_of_work.rollback_count == 1


def test_policy_rule_review_command_delegates_without_using_knowledge_ledger() -> None:
    target = KnowledgeReviewTargetRef(
        kind=KnowledgeReviewTargetKind.POLICY_RULE,
        object_id="policy-rule:" + "e" * 64,
        revision=1,
        revision_hash="f" * 64,
    )
    command = _command(target, KnowledgeReviewAction.APPROVE)
    current = _claim()
    policy_port = _PolicyApprovalPort()
    workflow, _, actions, unit_of_work, authorizer = _workflow(
        current,
        policy_approval_port=policy_port,
    )

    result = workflow.apply(command)

    assert isinstance(result, KnowledgeReviewPolicyDecision)
    assert result.target == target
    assert policy_port.commands == [command]
    assert actions.append_count == 0
    assert unit_of_work.commit_count == 0
    assert authorizer.calls == []


def test_policy_rule_review_without_owner_port_fails_closed() -> None:
    target = KnowledgeReviewTargetRef(
        kind=KnowledgeReviewTargetKind.POLICY_RULE,
        object_id="policy-rule:fourth-exam-route",
        revision=1,
        revision_hash="f" * 64,
    )
    workflow, _, actions, unit_of_work, _ = _workflow(_claim())

    with pytest.raises(AndromedaValidationError, match="not configured"):
        workflow.apply(_command(target, KnowledgeReviewAction.APPROVE))

    assert actions.append_count == 0
    assert unit_of_work.commit_count == 0

    with pytest.raises(PydanticValidationError, match="only policy-owned approve/reject"):
        _command(target, KnowledgeReviewAction.EDIT, edited_claim=_claim(revision=2))


def test_policy_approval_adapter_calls_existing_owner_command_and_returns_owner_event_ref() -> None:
    target = KnowledgeReviewTargetRef(
        kind=KnowledgeReviewTargetKind.POLICY_RULE,
        object_id="policy-rule:fourth-exam-route",
        revision=3,
        revision_hash="f" * 64,
    )
    command = _command(target, KnowledgeReviewAction.APPROVE)
    owner_commands = _PolicyApprovalCommands()
    preview = object()

    result = PolicyApprovalReviewAdapter(owner_commands).decide(
        command,
        review_preview=preview,  # type: ignore[arg-type]
    )  # type: ignore[arg-type]

    assert owner_commands.commands == [
        PolicyApprovalCommand(
            rule_id=target.object_id,
            revision=target.revision,
            revision_hash=target.revision_hash,
            kind=PolicyApprovalEventKind.APPROVED,
            actor_account_id=command.actor_account_id,
            reason=command.reason,
            recorded_at=command.recorded_at,
            preview_fingerprint=command.policy_preview_fingerprint,
        )
    ]
    assert result.target == target
    assert result.approval_event_id.startswith("policy-approval-event:")
    assert result.status is KnowledgeReviewPolicyDecisionStatus.APPROVED
    assert owner_commands.review_previews == [preview]


def test_policy_approval_adapter_rejects_approval_without_reviewed_preview() -> None:
    target = KnowledgeReviewTargetRef(
        kind=KnowledgeReviewTargetKind.POLICY_RULE,
        object_id="policy-rule:fourth-exam-route",
        revision=3,
        revision_hash="f" * 64,
    )
    command = _command(target, KnowledgeReviewAction.APPROVE)
    owner_commands = _PolicyApprovalCommands()

    with pytest.raises(AndromedaValidationError, match="reviewed preview gate"):
        PolicyApprovalReviewAdapter(owner_commands).decide(command)  # type: ignore[arg-type]

    assert owner_commands.commands == []
