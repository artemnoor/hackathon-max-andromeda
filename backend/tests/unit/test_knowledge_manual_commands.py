from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from andromeda.infrastructure.repositories.knowledge_manual_auth import (
    UniversityPolicySubmissionOnlyAuthorizer,
)
from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    BitemporalRevision,
    Claim,
    ClaimedPolicyStage,
    ClaimEvidenceLink,
    ClaimEvidenceRelationship,
    ClaimExtractionMethod,
    ClaimProposition,
    ClaimReviewState,
    ClaimRevisionRef,
    ClaimSubjectKind,
    ClaimValueText,
    EvidenceLocator,
    EvidenceRef,
    KnowledgeManualSubmission,
    KnowledgeSourceKind,
    ManualClaimMetadataCorrection,
    ManualSubmissionKind,
    SourceAllowedRoute,
    SourceMilestones,
    SourceReliabilityTier,
    TemporalInterval,
    claim_id_for_source_assertion,
    knowledge_review_target_ref,
    manual_request_fingerprint,
    manual_submission_id,
)
from andromeda.modules.knowledge.services.manual_source_commands import (
    MAX_MANUAL_DOCUMENT_BYTES,
    ManualSourceCommands,
    _validate_manual_document,
)
from andromeda.modules.policy.contracts.approval import PolicyApprovalCapability
from andromeda.modules.policy.contracts.rule import (
    DomainRuleRef,
    PolicyAuthorityLevel,
    PolicyDomainOwner,
    PolicyRevisionLifecycle,
    PolicyRuleRevision,
    PolicyRuleRevisionFields,
    PolicyScope,
    PolicyScopeLevel,
)
from andromeda.modules.policy.contracts.rule_ast import (
    PolicyContextField,
    PolicySelectorAst,
    PolicySelectorNode,
    PolicySelectorNodeKind,
)
from andromeda.modules.policy.contracts.temporal import PolicyTemporalRevision
from andromeda.modules.policy.domain.rule import create_policy_rule_revision
from andromeda.modules.policy.services.manual_submission import (
    ManualPolicyCandidateCommands,
)
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

ACTOR_ID = "account:" + "a" * 32
UNIVERSITY_ID = "university:bmstu"
NOW = datetime(2027, 12, 15, 12, tzinfo=UTC)
OBSERVATION_ID = "source-observation:" + "b" * 32
SOURCE_ID = "source:bmstu-admission"
SOURCE_URL = "https://priem.bmstu.ru/admission/rules.pdf"
ASSERTION = "A candidate statement from the university source."


class _Candidates:
    def __init__(self, claim: Claim) -> None:
        self.claims = {(claim.claim_id, claim.clock.revision): claim}

    def get_claim_revision(self, claim_id: str, revision: int) -> Claim | None:
        return self.claims.get((claim_id, revision))

    def append_claim_candidate(self, claim: Claim) -> Claim:
        if (claim.claim_id, claim.clock.revision) in self.claims:
            assert self.claims[(claim.claim_id, claim.clock.revision)] == claim
        else:
            assert (claim.claim_id, claim.clock.revision - 1) in self.claims
            self.claims[(claim.claim_id, claim.clock.revision)] = claim
        return claim


class _Submissions:
    def __init__(self, submission: KnowledgeManualSubmission) -> None:
        self.rows = [submission]

    def get_by_idempotency_key(
        self, actor_account_id: str, idempotency_key: str
    ) -> KnowledgeManualSubmission | None:
        return next(
            (
                item
                for item in self.rows
                if item.actor_account_id == actor_account_id
                and item.idempotency_key == idempotency_key
            ),
            None,
        )

    def get_latest_for_target(self, target_id: str) -> KnowledgeManualSubmission | None:
        candidates = [item for item in self.rows if item.target_id == target_id]
        return max(candidates, key=lambda item: item.target_revision, default=None)

    def append_submission(self, submission: KnowledgeManualSubmission) -> KnowledgeManualSubmission:
        self.rows.append(submission)
        return submission


class _Authorization:
    def require_source_steward(self, _actor_account_id: str) -> None:
        raise AssertionError("source-steward authorization is not used in this test")

    def require_university_editor(self, actor_account_id: str, university_id: str) -> None:
        if actor_account_id != ACTOR_ID or university_id != UNIVERSITY_ID:
            raise NotFoundError("Resource was not found")


class _SourceStewardAuthorization:
    def require_source_steward(self, actor_account_id: str) -> None:
        if actor_account_id != ACTOR_ID:
            raise NotFoundError("Resource was not found")

    def require_university_editor(self, _actor_account_id: str, _university_id: str) -> None:
        raise AssertionError("university editor authorization is not used in this test")


class _UnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _UniversityAccess:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def require(self, actor_account_id: str, university_id: str, _minimum_role: object) -> None:
        self.calls.append((actor_account_id, university_id))


class _PolicyApproval:
    def __init__(self) -> None:
        self.submissions: list[object] = []

    def submit(self, submission: object) -> SimpleNamespace:
        self.submissions.append(submission)
        return SimpleNamespace(
            actor_account_id=ACTOR_ID,
            reason="University proposes this change",
        )


def _manual_claim() -> Claim:
    digest = hashlib.sha256(ASSERTION.encode()).hexdigest()
    evidence = EvidenceRef(
        source_id=SOURCE_ID,
        source_observation_id=OBSERVATION_ID,
        snapshot_sha256="c" * 64,
        source_url=SOURCE_URL,
        locator=EvidenceLocator(page=2, section="Admission rules"),
    )
    return Claim(
        claim_id=claim_id_for_source_assertion(OBSERVATION_ID, 4, 4 + len(ASSERTION), digest),
        clock=BitemporalRevision(
            revision=1,
            valid_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
            recorded_at=NOW,
        ),
        source_observation_id=OBSERVATION_ID,
        text_start_offset=4,
        text_end_offset=4 + len(ASSERTION),
        assertion_text=ASSERTION,
        assertion_text_sha256=digest,
        proposition=ClaimProposition(
            predicate="admission.notice",
            subject_kind=ClaimSubjectKind.UNIVERSITY,
            subject_id=UNIVERSITY_ID,
            value=ClaimValueText(kind="text", value="Old interpretation"),
        ),
        claimed_stage=ClaimedPolicyStage.ANNOUNCED,
        review_state=ClaimReviewState.NEEDS_REVIEW,
        source_milestones=SourceMilestones(published_at=NOW, captured_at=NOW),
        extraction_method=ClaimExtractionMethod.MANUAL,
        extractor_id="manual-operator",
        extractor_version="v1",
        evidence=(
            ClaimEvidenceLink(
                relationship=ClaimEvidenceRelationship.ORIGINATES_FROM,
                evidence=evidence,
            ),
        ),
    )


def _initial_submission(claim: Claim) -> KnowledgeManualSubmission:
    key = hashlib.sha256(b"initial").hexdigest()
    fingerprint = manual_request_fingerprint({"initial": claim.claim_id})
    target = knowledge_review_target_ref(claim)
    return KnowledgeManualSubmission(
        submission_id=manual_submission_id(
            actor_account_id=ACTOR_ID,
            idempotency_key=key,
            request_fingerprint=fingerprint,
        ),
        kind=ManualSubmissionKind.CLAIM_CANDIDATE,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        actor_account_id=ACTOR_ID,
        university_id=UNIVERSITY_ID,
        reason="Initial manual source assertion",
        target_id=claim.claim_id,
        target_revision=claim.clock.revision,
        target_hash=target.revision_hash,
        source_observation_id=claim.source_observation_id,
        recorded_at=NOW,
    )


def _commands(
    claim: Claim,
) -> tuple[ManualSourceCommands, _Submissions, _UnitOfWork]:
    submissions = _Submissions(_initial_submission(claim))
    unit_of_work = _UnitOfWork()
    commands = ManualSourceCommands(
        sources=None,  # type: ignore[arg-type]
        candidates=_Candidates(claim),  # type: ignore[arg-type]
        submissions=submissions,
        authorizer=_Authorization(),
        capture=None,  # type: ignore[arg-type]
        unit_of_work=unit_of_work,
    )
    return commands, submissions, unit_of_work


def test_manual_claim_metadata_correction_appends_pending_revision_and_audit() -> None:
    claim = _manual_claim()
    commands, submissions, unit_of_work = _commands(claim)
    proposition = ClaimProposition(
        predicate="admission.notice",
        subject_kind=ClaimSubjectKind.UNIVERSITY,
        subject_id=UNIVERSITY_ID,
        value=ClaimValueText(kind="text", value="Corrected interpretation"),
    )
    correction = ManualClaimMetadataCorrection(
        claim_id=claim.claim_id,
        expected_revision=claim.clock.revision,
        expected_revision_hash=knowledge_review_target_ref(claim).revision_hash,
        proposition=proposition,
        claimed_stage=ClaimedPolicyStage.PROPOSAL,
        reason="Corrected classification after checking the cited page",
        idempotency_key="manual-correction-key-0001",
    )

    revised = commands.correct_claim_metadata(
        actor_account_id=ACTOR_ID,
        university_id=UNIVERSITY_ID,
        correction=correction,
        now=NOW.replace(minute=1),
    )

    assert revised.clock.revision == 2
    assert revised.review_state is ClaimReviewState.NEEDS_REVIEW
    assert revised.proposition == proposition
    assert revised.evidence == claim.evidence
    assert revised.assertion_text == claim.assertion_text
    assert submissions.rows[-1].target_hash == knowledge_review_target_ref(revised).revision_hash
    assert submissions.rows[-1].reason == correction.reason
    assert unit_of_work.commits == 1


def test_manual_claim_metadata_correction_rejects_stale_hash_and_wrong_scope() -> None:
    claim = _manual_claim()
    commands, submissions, unit_of_work = _commands(claim)
    correction = ManualClaimMetadataCorrection(
        claim_id=claim.claim_id,
        expected_revision=1,
        expected_revision_hash="f" * 64,
        claimed_stage=ClaimedPolicyStage.PROPOSAL,
        reason="Correction",
        idempotency_key="manual-correction-key-0002",
    )

    with pytest.raises(ConflictError, match="stale claim revision"):
        commands.correct_claim_metadata(
            actor_account_id=ACTOR_ID,
            university_id=UNIVERSITY_ID,
            correction=correction,
            now=NOW.replace(minute=1),
        )
    assert len(submissions.rows) == 1
    assert unit_of_work.commits == 0

    valid_hash = knowledge_review_target_ref(claim).revision_hash
    wrong_scope = correction.model_copy(update={"expected_revision_hash": valid_hash})
    with pytest.raises(NotFoundError):
        commands.correct_claim_metadata(
            actor_account_id=ACTOR_ID,
            university_id="university:other",
            correction=wrong_scope,
            now=NOW.replace(minute=1),
        )


def _policy_revision(university_id: str) -> PolicyRuleRevision:
    future = datetime(2028, 9, 1, tzinfo=UTC)
    return create_policy_rule_revision(
        PolicyRuleRevisionFields(
            rule_id="policy-rule:manual-bmstu-rule",
            revision=1,
            schema_version="policy-rule.v3",
            family_id="policy-family:manual-admission-benefit",
            authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
            selector=PolicySelectorAst(
                nodes=(
                    PolicySelectorNode(
                        node_id="university",
                        kind=PolicySelectorNodeKind.EQUALS,
                        field=PolicyContextField.UNIVERSITY_ID,
                        value=university_id,
                    ),
                )
            ),
            scope=PolicyScope(level=PolicyScopeLevel.UNIVERSITY, scope_id=university_id),
            domain_rule=DomainRuleRef(
                owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
                canonical_rule_id="admission-benefit:manual-confirmation",
                owner_revision=1,
                owner_revision_hash="a" * 64,
            ),
            lifecycle=PolicyRevisionLifecycle.FUTURE_EFFECTIVE,
            temporal=PolicyTemporalRevision(
                clock=BitemporalRevision(
                    revision=1,
                    valid_time=TemporalInterval(start=future),
                    recorded_at=NOW,
                ),
                source_milestones=SourceMilestones(
                    published_at=NOW,
                    captured_at=NOW,
                    effective_time=TemporalInterval(start=future),
                ),
            ),
            source_claims=(ClaimRevisionRef(claim_id="claim:" + "d" * 64, revision=1),),
            evidence=(
                EvidenceRef(
                    source_id=SOURCE_ID,
                    source_observation_id=OBSERVATION_ID,
                    snapshot_sha256="c" * 64,
                    source_url=SOURCE_URL,
                    locator=EvidenceLocator(section="Admission rules"),
                ),
            ),
        )
    )


def test_manual_policy_candidate_is_university_scoped_and_pending_only() -> None:
    approval = _PolicyApproval()
    commands = ManualPolicyCandidateCommands(
        approval_commands=approval,  # type: ignore[arg-type]
        authorizer=_Authorization(),
    )
    revision = _policy_revision(UNIVERSITY_ID)

    event = commands.submit(
        actor_account_id=ACTOR_ID,
        university_id=UNIVERSITY_ID,
        revision=revision,
        reason="University proposes this change",
        submitted_at=NOW,
    )

    assert event.reason == "University proposes this change"
    assert len(approval.submissions) == 1
    assert approval.submissions[0].revision == revision

    with pytest.raises(ValidationError, match="exact university"):
        commands.submit(
            actor_account_id=ACTOR_ID,
            university_id=UNIVERSITY_ID,
            revision=_policy_revision("university:other"),
            reason="Out of scope proposal",
            submitted_at=NOW,
        )
    assert len(approval.submissions) == 1


def test_university_policy_authorizer_allows_submission_but_denies_approval() -> None:
    access = _UniversityAccess()
    authorizer = UniversityPolicySubmissionOnlyAuthorizer(
        university_access=access,  # type: ignore[arg-type]
        actor_account_id=ACTOR_ID,
        university_id=UNIVERSITY_ID,
    )

    authorizer.require_capability(ACTOR_ID, PolicyApprovalCapability.SUBMIT_REVISION)
    with pytest.raises(NotFoundError):
        authorizer.require_capability(ACTOR_ID, PolicyApprovalCapability.APPROVE_REVISION)
    with pytest.raises(NotFoundError):
        authorizer.require_capability(
            "account:" + "e" * 32, PolicyApprovalCapability.SUBMIT_REVISION
        )
    assert access.calls == [(ACTOR_ID, UNIVERSITY_ID)]


def test_manual_document_upload_is_bounded_and_never_fetches_unapproved_url() -> None:
    registry = ApprovedSourceRegistryRevision(
        source_id=SOURCE_ID,
        revision=1,
        source_kind=KnowledgeSourceKind.UNIVERSITY_ADMISSION_RULES,
        reliability_tier=SourceReliabilityTier.OFFICIAL_UNIVERSITY,
        adapter_id="bmstu_admission_rules",
        adapter_version="v1",
        start_url=SOURCE_URL,
        allowlist=(SourceAllowedRoute(host="priem.bmstu.ru", path_prefix="/admission"),),
        poll_interval_seconds=86_400,
        freshness_budget_seconds=604_800,
        enabled=False,
        approved_by_account_id=ACTOR_ID,
        approved_at=NOW,
        approval_reason="Test source",
        recorded_at=NOW,
    )

    class _Sources:
        def get_latest_registry_revision(self, _source_id: str) -> ApprovedSourceRegistryRevision:
            return registry

    class _Capture:
        calls = 0

        def capture(self, **_kwargs: object) -> None:
            self.calls += 1

    class _EmptySubmissions:
        def get_by_idempotency_key(
            self, _actor_account_id: str, _idempotency_key: str
        ) -> None:
            return None

    capture = _Capture()
    commands = ManualSourceCommands(
        sources=_Sources(),  # type: ignore[arg-type]
        candidates=None,  # type: ignore[arg-type]
        submissions=_EmptySubmissions(),  # type: ignore[arg-type]
        authorizer=_SourceStewardAuthorization(),
        capture=capture,  # type: ignore[arg-type]
        unit_of_work=_UnitOfWork(),
    )

    with pytest.raises(ValidationError, match="outside the approved source allowlist"):
        commands.attach_document(
            actor_account_id=ACTOR_ID,
            source_id=SOURCE_ID,
            requested_url="https://unapproved.example/admission/rules.pdf",
            content_type="application/pdf",
            body=b"%PDF-1.4\nmanual test",
            reason="Uploaded source material",
            idempotency_key="manual-upload-key-0001",
            expires_at=None,
            now=NOW,
        )
    assert capture.calls == 0

    with pytest.raises(ValidationError, match="accept only PDF"):
        _validate_manual_document(b"<html>payload</html>", "text/html")
    with pytest.raises(ValidationError, match="10 MiB"):
        _validate_manual_document(b"x" * (MAX_MANUAL_DOCUMENT_BYTES + 1), "text/plain")
