from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy import event, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.base import Base, create_engine_for_url
from andromeda.infrastructure.database.models import (
    AccountModel,
    IngestRunModel,
    KnowledgeChangeEventModel,
    KnowledgeClaimCandidateClusterMemberModel,
    KnowledgeClaimCandidateClusterModel,
    KnowledgeClaimEvidenceModel,
    KnowledgeClaimModel,
    KnowledgeConflictEventModel,
    KnowledgeConflictEvidenceModel,
    KnowledgeConflictGroupModel,
    KnowledgeConflictParticipantModel,
    PolicyApprovalEventModel,
    PolicyRuleRelationModel,
    PolicyRuleRevisionModel,
    SourceSnapshotModel,
)
from andromeda.infrastructure.repositories.knowledge_candidates import (
    SqlAlchemyKnowledgeCandidateRepository,
)
from andromeda.infrastructure.repositories.knowledge_conflicts import (
    SqlAlchemyConflictGroupRepository,
)
from andromeda.infrastructure.repositories.knowledge_relations import (
    SqlAlchemyKnowledgeRelationRepository,
)
from andromeda.infrastructure.repositories.knowledge_source_repository import (
    SqlAlchemyKnowledgeSourceRepository,
)
from andromeda.infrastructure.repositories.policy import SqlAlchemyPolicyRuleRepository
from andromeda.modules.admission_fit.contracts.public import AdmissionFitSearchGateway
from andromeda.modules.admissions.contracts.admission_cycles import (
    AdmissionCycle,
    AdmissionCycleResolution,
    AdmissionCycleResolutionStatus,
    AdmissionCycleState,
    InclusiveDateWindow,
)
from andromeda.modules.analytics.services.executor import AnalyticsExecutor
from andromeda.modules.conversation.services.assistant import AssistantService
from andromeda.modules.conversation.services.engine import ConversationEngine
from andromeda.modules.conversation.services.rule_decision_policy import (
    RuleBasedDecisionPolicy,
)
from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    BitemporalRevision,
    ChangeEvent,
    ChangeEventKind,
    Claim,
    ClaimCandidateCluster,
    ClaimedPolicyStage,
    ClaimEvidenceLink,
    ClaimEvidenceRelationship,
    ClaimExtractionMethod,
    ClaimProposition,
    ClaimReviewState,
    ClaimRevisionRef,
    ClaimSubjectKind,
    ClaimValueBoolean,
    ClaimValueDecimal,
    ConflictParticipantKind,
    ConflictParticipantReference,
    ConflictParticipantRole,
    ConflictValidInterval,
    EvidenceLocator,
    EvidenceRef,
    KnowledgeClaimRelationRevision,
    KnowledgeClaimRelationRevisionFields,
    KnowledgeConflictEventKind,
    KnowledgeConflictGroupRevision,
    KnowledgeConflictGroupRevisionFields,
    KnowledgeConflictKind,
    KnowledgeConflictParticipant,
    KnowledgeConflictScope,
    KnowledgeConflictScopeLevel,
    KnowledgeConflictState,
    KnowledgeRelationKind,
    KnowledgeRelationReviewState,
    KnowledgeSourceKind,
    SourceAllowedRoute,
    SourceIdentity,
    SourceJurisdiction,
    SourceMilestones,
    SourceObservation,
    SourceReliabilityTier,
    TemporalInterval,
    change_event_id_for_claims,
    claim_id_for_source_assertion,
    create_knowledge_conflict_event,
    knowledge_conflict_content_hash,
    knowledge_conflict_group_id,
    knowledge_relation_content_hash,
    knowledge_relation_id,
)
from andromeda.modules.knowledge.domain.claim_fingerprint import fingerprint_claim
from andromeda.modules.knowledge.domain.sources import (
    observation_id_from_idempotency_key,
    observation_idempotency_key,
)
from andromeda.modules.policy.contracts.applicability import (
    PolicyDomainLookupStatus,
    PolicyDomainRuleLookup,
)
from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalCapability,
    PolicyApprovalCommand,
    PolicyApprovalEventKind,
    PolicyApprovalState,
    PolicyRuleSubmission,
)
from andromeda.modules.policy.contracts.resolution import PolicyResolutionRequest
from andromeda.modules.policy.contracts.rule import (
    DomainRuleRef,
    PolicyAuthorityLevel,
    PolicyDomainOwner,
    PolicyRevisionLifecycle,
    PolicyRuleRelation,
    PolicyRuleRelationKind,
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
from andromeda.modules.policy.domain.approval import derive_approval_state
from andromeda.modules.policy.domain.rule import create_policy_rule_revision
from andromeda.modules.policy.services.approval import PolicyApprovalCommandService
from andromeda.modules.policy.services.effective_rule_resolver import (
    EffectivePolicyResolver,
)
from andromeda.modules.policy.services.ports import (
    PolicyAdmissionCycleReader,
    PolicyClock,
    PolicyDomainRuleReader,
)
from andromeda.modules.presentation.services.rule_response_policy import (
    RuleBasedResponsePolicy,
)
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.shared.contracts.errors import ConflictError, ValidationError

CAPTURED = datetime(2027, 12, 15, 12, tzinfo=UTC)
RECORDED = CAPTURED + timedelta(minutes=1)
ACCOUNT_ID = "account:" + "a" * 32
SOURCE_ID = "source:ministry-admission"
ISSUER_ID = "issuer:ministry"
RUN_ID = "ingest:" + "b" * 32
BODY = b"proposal for new minimum admission exam score"
SNAPSHOT_HASH = hashlib.sha256(BODY).hexdigest()
SOURCE_URL = "https://official.example/admission/proposal.pdf"
ASSERTION = "The ministry proposed a new minimum exam score."


def _source_evidence(session: Session) -> EvidenceRef:
    session.add(
        AccountModel(
            account_id=ACCOUNT_ID,
            email="claim-reviewer@example.test",
            password_hash="test-hash",
            created_at=CAPTURED,
            updated_at=CAPTURED,
        )
    )
    session.add(IngestRunModel(id=RUN_ID, started_at=CAPTURED, status="completed"))
    session.flush()
    session.add(
        SourceSnapshotModel(
            content_sha256=SNAPSHOT_HASH,
            ingest_run_id=RUN_ID,
            source_kind="official_ministry_proposal",
            requested_url=SOURCE_URL,
            final_url=SOURCE_URL,
            status_code=200,
            content_type="application/pdf",
            captured_at=CAPTURED,
            body=BODY,
        )
    )
    session.flush()
    source_repository = SqlAlchemyKnowledgeSourceRepository(session)
    source_repository.register_source_identity(
        SourceIdentity(
            source_id=SOURCE_ID,
            issuer_id=ISSUER_ID,
            jurisdiction=SourceJurisdiction.FEDERAL,
            identity_key="minimum-ege-proposal",
            display_name="Official Ministry proposal",
            created_at=CAPTURED,
        )
    )
    source_repository.append_approved_registry_revision(
        ApprovedSourceRegistryRevision(
            source_id=SOURCE_ID,
            revision=1,
            source_kind=KnowledgeSourceKind.MINISTRY_PUBLICATION,
            reliability_tier=SourceReliabilityTier.OFFICIAL_ISSUER,
            adapter_id="ministry_docs",
            adapter_version="v1",
            start_url=SOURCE_URL,
            allowlist=(
                SourceAllowedRoute(host="official.example", path_prefix="/admission"),
            ),
            poll_interval_seconds=86_400,
            freshness_budget_seconds=604_800,
            enabled=True,
            approved_by_account_id=ACCOUNT_ID,
            approved_at=CAPTURED,
            approval_reason="Official ministry source is allowlisted for this test.",
            recorded_at=CAPTURED,
        )
    )
    idempotency_key = observation_idempotency_key(
        source_id=SOURCE_ID,
        registry_revision=1,
        ingest_run_id=RUN_ID,
        requested_url=SOURCE_URL,
        snapshot_sha256=SNAPSHOT_HASH,
    )
    observation = SourceObservation(
        source_observation_id=observation_id_from_idempotency_key(idempotency_key),
        source_id=SOURCE_ID,
        registry_revision=1,
        idempotency_key=idempotency_key,
        ingest_run_id=RUN_ID,
        snapshot_sha256=SNAPSHOT_HASH,
        requested_url=SOURCE_URL,
        final_url=SOURCE_URL,
        status_code=200,
        content_type="application/pdf",
        response_class="success",
        access_mode="http",
        truncated=False,
        captured_at=CAPTURED,
        observed_at=CAPTURED + timedelta(seconds=1),
    )
    source_repository.record_observation(observation)
    return EvidenceRef(
        source_id=SOURCE_ID,
        source_observation_id=observation.source_observation_id,
        snapshot_sha256=SNAPSHOT_HASH,
        source_url=SOURCE_URL,
        locator=EvidenceLocator(page=2, section="Proposed minimum scores"),
    )


def _secondary_source_evidence(session: Session) -> EvidenceRef:
    source_id = "source:regulator-mirror"
    run_id = "ingest:" + "d" * 32
    session.add(IngestRunModel(id=run_id, started_at=CAPTURED, status="completed"))
    session.flush()
    source_repository = SqlAlchemyKnowledgeSourceRepository(session)
    source_repository.register_source_identity(
        SourceIdentity(
            source_id=source_id,
            issuer_id="issuer:regulator-mirror",
            jurisdiction=SourceJurisdiction.FEDERAL,
            identity_key="mirrored-minimum-score-notice",
            display_name="Official regulator mirror",
            created_at=CAPTURED,
        )
    )
    source_repository.append_approved_registry_revision(
        ApprovedSourceRegistryRevision(
            source_id=source_id,
            revision=1,
            source_kind=KnowledgeSourceKind.MINISTRY_PUBLICATION,
            reliability_tier=SourceReliabilityTier.OFFICIAL_ISSUER,
            adapter_id="ministry_docs",
            adapter_version="v1",
            start_url=SOURCE_URL,
            allowlist=(
                SourceAllowedRoute(host="official.example", path_prefix="/admission"),
            ),
            poll_interval_seconds=86_400,
            freshness_budget_seconds=604_800,
            enabled=True,
            approved_by_account_id=ACCOUNT_ID,
            approved_at=CAPTURED,
            approval_reason="Second official publication provides independent evidence.",
            recorded_at=CAPTURED,
        )
    )
    idempotency_key = observation_idempotency_key(
        source_id=source_id,
        registry_revision=1,
        ingest_run_id=run_id,
        requested_url=SOURCE_URL,
        snapshot_sha256=SNAPSHOT_HASH,
    )
    observation = SourceObservation(
        source_observation_id=observation_id_from_idempotency_key(idempotency_key),
        source_id=source_id,
        registry_revision=1,
        idempotency_key=idempotency_key,
        ingest_run_id=run_id,
        snapshot_sha256=SNAPSHOT_HASH,
        requested_url=SOURCE_URL,
        final_url=SOURCE_URL,
        status_code=200,
        content_type="application/pdf",
        response_class="success",
        access_mode="http",
        truncated=False,
        captured_at=CAPTURED,
        observed_at=CAPTURED + timedelta(seconds=2),
    )
    source_repository.record_observation(observation)
    return EvidenceRef(
        source_id=source_id,
        source_observation_id=observation.source_observation_id,
        snapshot_sha256=SNAPSHOT_HASH,
        source_url=SOURCE_URL,
        locator=EvidenceLocator(page=2, section="Proposed minimum scores"),
    )


def _claim(
    evidence: EvidenceRef,
    *,
    revision: int = 1,
    recorded_at: datetime = RECORDED,
    assertion: str = ASSERTION,
    start_offset: int = 120,
    predicate: str = "admission.minimum_ege_score",
    subject_kind: ClaimSubjectKind = ClaimSubjectKind.EXAM,
    subject_id: str = "subject:mathematics",
    value: Decimal | bool = Decimal(80),
    unit: str | None = "score",
) -> Claim:
    text_hash = hashlib.sha256(assertion.encode("utf-8")).hexdigest()
    return Claim(
        claim_id=claim_id_for_source_assertion(
            evidence.source_observation_id,
            start_offset,
            start_offset + len(assertion),
            text_hash,
        ),
        clock=BitemporalRevision(
            revision=revision,
            valid_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
            recorded_at=recorded_at,
        ),
        source_observation_id=evidence.source_observation_id,
        text_start_offset=start_offset,
        text_end_offset=start_offset + len(assertion),
        assertion_text=assertion,
        assertion_text_sha256=text_hash,
        proposition=ClaimProposition(
            predicate=predicate,
            subject_kind=subject_kind,
            subject_id=subject_id,
            value=(
                ClaimValueBoolean(kind="boolean", value=value)
                if isinstance(value, bool)
                else ClaimValueDecimal(kind="decimal", value=value)
            ),
            unit=unit,
        ),
        claimed_stage=ClaimedPolicyStage.PROPOSAL,
        source_milestones=SourceMilestones(published_at=CAPTURED, captured_at=CAPTURED),
        extraction_method=ClaimExtractionMethod.DETERMINISTIC_PARSER,
        extractor_id="ministry_pdf_rules",
        extractor_version=f"v{revision}",
        evidence=(
            ClaimEvidenceLink(
                relationship=ClaimEvidenceRelationship.ORIGINATES_FROM,
                evidence=evidence,
            ),
        ),
    )


def _policy_revision(
    evidence: EvidenceRef,
    claim: Claim,
    *,
    domain_rule: DomainRuleRef | None = None,
) -> PolicyRuleRevision:
    return create_policy_rule_revision(
        PolicyRuleRevisionFields(
            rule_id="policy-rule:bmstu-fourth-exam",
            revision=1,
            schema_version="policy-rule.v3",
            family_id="policy-family:fourth-exam-benefit",
            authority=PolicyAuthorityLevel.REGULATOR_NORMATIVE,
            selector=PolicySelectorAst(
                nodes=(
                    PolicySelectorNode(
                        node_id="university",
                        kind=PolicySelectorNodeKind.EQUALS,
                        field=PolicyContextField.UNIVERSITY_ID,
                        value="university:bmstu",
                    ),
                )
            ),
            scope=PolicyScope(
                level=PolicyScopeLevel.UNIVERSITY,
                scope_id="university:bmstu",
            ),
            domain_rule=domain_rule
            or DomainRuleRef(
                owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
                canonical_rule_id="admission-benefit:minimum-confirmation",
                owner_revision=1,
                owner_revision_hash="b" * 64,
            ),
            lifecycle=PolicyRevisionLifecycle.FUTURE_EFFECTIVE,
            temporal=PolicyTemporalRevision(
                clock=BitemporalRevision(
                    revision=1,
                    valid_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
                    recorded_at=RECORDED + timedelta(seconds=1),
                ),
                source_milestones=SourceMilestones(
                    published_at=CAPTURED,
                    captured_at=CAPTURED,
                    effective_time=TemporalInterval(
                        start=datetime(2028, 9, 1, tzinfo=UTC)
                    ),
                ),
            ),
            source_claims=(
                ClaimRevisionRef(
                    claim_id=claim.claim_id, revision=claim.clock.revision
                ),
            ),
            evidence=(evidence,),
        )
    )


def test_policy_relation_persists_exact_approved_target_and_source_provenance() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            evidence = _source_evidence(session)
            candidate_repository = SqlAlchemyKnowledgeCandidateRepository(session)
            claim = _claim(evidence)
            candidate_repository.append_claim_candidate(claim)
            session.execute(
                update(KnowledgeClaimModel)
                .where(
                    KnowledgeClaimModel.claim_id == claim.claim_id,
                    KnowledgeClaimModel.revision == claim.clock.revision,
                )
                .values(review_state="accepted_as_source_assertion")
            )
            session.commit()

            class AllowPolicyCapabilities:
                @staticmethod
                def require_capability(
                    actor_account_id: str, capability: PolicyApprovalCapability
                ) -> None:
                    assert actor_account_id == ACCOUNT_ID
                    assert capability in {
                        PolicyApprovalCapability.SUBMIT_REVISION,
                        PolicyApprovalCapability.APPROVE_REVISION,
                    }

            policy_repository = SqlAlchemyPolicyRuleRepository(session)
            service = PolicyApprovalCommandService(
                repository=policy_repository,
                authorizer=AllowPolicyCapabilities(),
                unit_of_work=session,
            )
            target = _policy_revision(evidence, claim)
            service.submit(
                PolicyRuleSubmission(
                    revision=target,
                    submitted_by_account_id=ACCOUNT_ID,
                    reason="Submit the source-backed baseline rule.",
                    submitted_at=RECORDED + timedelta(seconds=2),
                )
            )
            service._append_decision(
                PolicyApprovalCommand(
                    rule_id=target.rule_id,
                    revision=target.revision,
                    revision_hash=target.content_hash,
                    kind=PolicyApprovalEventKind.APPROVED,
                    actor_account_id=ACCOUNT_ID,
                    reason="Approve the exact reviewed baseline revision.",
                    recorded_at=RECORDED + timedelta(seconds=3),
                    preview_fingerprint="a" * 64,
                )
            )

            exception_fields = PolicyRuleRevisionFields(
                rule_id="policy-rule:bmstu-exam-exception",
                revision=1,
                schema_version="policy-rule.v3",
                family_id=target.family_id,
                authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
                selector=PolicySelectorAst(
                    nodes=(
                        PolicySelectorNode(
                            node_id="university",
                            kind=PolicySelectorNodeKind.EQUALS,
                            field=PolicyContextField.UNIVERSITY_ID,
                            value="university:bmstu",
                        ),
                    )
                ),
                scope=PolicyScope(
                    level=PolicyScopeLevel.PROGRAM,
                    scope_id="program:bmstu:example",
                ),
                domain_rule=DomainRuleRef(
                    owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
                    canonical_rule_id="admission-benefit:minimum-confirmation",
                    owner_revision=1,
                    owner_revision_hash="b" * 64,
                ),
                lifecycle=PolicyRevisionLifecycle.FUTURE_EFFECTIVE,
                temporal=PolicyTemporalRevision(
                    clock=BitemporalRevision(
                        revision=1,
                        valid_time=TemporalInterval(start=RECORDED),
                        recorded_at=RECORDED + timedelta(seconds=4),
                    ),
                    source_milestones=SourceMilestones(
                        published_at=CAPTURED,
                        captured_at=CAPTURED,
                        effective_time=TemporalInterval(
                            start=datetime(2028, 9, 1, tzinfo=UTC)
                        ),
                    ),
                ),
                source_claims=(ClaimRevisionRef(claim_id=claim.claim_id, revision=1),),
                evidence=(evidence,),
                relations=(
                    PolicyRuleRelation(
                        kind=PolicyRuleRelationKind.AUTHORIZED_EXCEPTION_TO,
                        target_rule_id=target.rule_id,
                        target_revision=target.revision,
                        target_hash=target.content_hash,
                        source_claim=ClaimRevisionRef(
                            claim_id=claim.claim_id, revision=1
                        ),
                        evidence=evidence,
                    ),
                ),
            )
            exception = create_policy_rule_revision(exception_fields)
            service.submit(
                PolicyRuleSubmission(
                    revision=exception,
                    submitted_by_account_id=ACCOUNT_ID,
                    reason="Link the approved university exception to the exact baseline.",
                    submitted_at=RECORDED + timedelta(seconds=5),
                )
            )

            assert policy_repository.get_revision(exception.rule_id, 1) == exception
            stored_relation = session.query(PolicyRuleRelationModel).one()
            assert stored_relation.relation_kind == "authorized_exception_to"
            assert stored_relation.target_rule_id == target.rule_id
            assert stored_relation.target_revision == target.revision
            assert stored_relation.target_hash == target.content_hash
            assert stored_relation.claim_ordinal == 0
            assert stored_relation.evidence_ordinal == 0
            assert session.query(PolicyApprovalEventModel).count() == 3
    finally:
        engine.dispose()


def test_source_claim_requires_exact_human_approval_before_assistant_resolution() -> (
    None
):
    """A captured source reaches the assistant only through an approved revision."""
    from andromeda.modules.conversation.contracts.assistant import PolicyAnswerStatus
    from andromeda.modules.policy.contracts.applicability import (
        PolicyDomainRuleLookup,
    )

    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2028, 9, 15, tzinfo=UTC)
    valid_as_of = datetime(2028, 9, 2, tzinfo=UTC)
    with Session(engine) as session:
        evidence = _source_evidence(session)
        claim_repository = SqlAlchemyKnowledgeCandidateRepository(session)
        claim = _claim(
            evidence,
            assertion="The ministry proposed a fourth EGE starting in 2028.",
            predicate="admission.exam.required_count",
            subject_id="exam:ege",
            value=Decimal(4),
            unit="exam_count",
        )
        claim_repository.append_claim_candidate(claim)
        session.execute(
            update(KnowledgeClaimModel)
            .where(
                KnowledgeClaimModel.claim_id == claim.claim_id,
                KnowledgeClaimModel.revision == claim.clock.revision,
            )
            .values(review_state=ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION.value)
        )
        session.commit()

        domain_rule = DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSIONS,
            canonical_rule_id="admission:bmstu-exam-count",
            owner_revision=1,
            owner_revision_hash="d" * 64,
        )
        revision = _policy_revision(evidence, claim, domain_rule=domain_rule)
        policies = SqlAlchemyPolicyRuleRepository(session)

        class Capabilities:
            @staticmethod
            def require_capability(actor_account_id, capability) -> None:
                assert actor_account_id == ACCOUNT_ID
                assert capability in {
                    PolicyApprovalCapability.SUBMIT_REVISION,
                    PolicyApprovalCapability.APPROVE_REVISION,
                }

        approvals = PolicyApprovalCommandService(
            repository=policies,
            authorizer=Capabilities(),
            unit_of_work=session,
        )
        approvals.submit(
            PolicyRuleSubmission(
                revision=revision,
                submitted_by_account_id=ACCOUNT_ID,
                reason="Submit the parsed source-backed candidate for review.",
                submitted_at=RECORDED + timedelta(seconds=2),
            )
        )

        cycle = AdmissionCycle(
            cycle_id="admission-cycle:bmstu:2028",
            revision=1,
            university_id="university:bmstu",
            admission_year=2028,
            academic_year="2028/2029",
            application_period=InclusiveDateWindow(
                start_date=datetime(2028, 6, 1, tzinfo=UTC).date(),
                end_date=datetime(2028, 7, 30, tzinfo=UTC).date(),
            ),
            enrollment_period=None,
            state=AdmissionCycleState.PUBLISHED,
            evidence=(evidence,),
            approved_by_account_id=ACCOUNT_ID,
            approved_at=RECORDED + timedelta(seconds=1),
            approval_reason="Use the captured official admission calendar.",
            recorded_at=RECORDED + timedelta(seconds=1),
        )

        class Cycles(PolicyAdmissionCycleReader):
            def resolve_for_admission(
                self, university_id, admission_year, *, as_known_at=None
            ) -> AdmissionCycleResolution:
                if (
                    university_id != cycle.university_id
                    or admission_year != cycle.admission_year
                    or (as_known_at is not None and cycle.recorded_at > as_known_at)
                ):
                    return AdmissionCycleResolution(
                        status=AdmissionCycleResolutionStatus.BLOCKED_BY_MISSING_DATA,
                        reason="No matching approved admission cycle is available.",
                    )
                return AdmissionCycleResolution(
                    status=AdmissionCycleResolutionStatus.RESOLVED,
                    cycle=cycle,
                )

        class Owner(PolicyDomainRuleReader):
            owner_module = PolicyDomainOwner.ADMISSIONS

            def __init__(self) -> None:
                self.lookups: list[DomainRuleRef] = []

            def lookup_rule(self, reference: DomainRuleRef) -> PolicyDomainRuleLookup:
                self.lookups.append(reference)
                return PolicyDomainRuleLookup(
                    requested_reference=reference,
                    resolved_reference=reference,
                    status=PolicyDomainLookupStatus.AVAILABLE,
                )

        class Clock(PolicyClock):
            def now(self) -> datetime:
                return now

        owner = Owner()
        resolver = EffectivePolicyResolver(
            policies=policies,
            admission_cycles=Cycles(),
            domain_readers=(owner,),
            clock=Clock(),
        )
        claim_ref = ClaimRevisionRef(claim_id=claim.claim_id, revision=1)
        request = PolicyResolutionRequest(
            university_id="university:bmstu",
            admission_year=2028,
            valid_as_of=valid_as_of,
            as_known_at=RECORDED + timedelta(seconds=2),
        )

        pending_trace = resolver.resolve_for_claims(request, (claim_ref,))
        assert pending_trace.effective_rules == ()
        assert pending_trace.status.value != "resolved"
        assert owner.lookups == []
        pending_events = policies.list_approval_events(
            revision.rule_id, revision.revision
        )
        assert tuple(item.kind for item in pending_events) == (
            PolicyApprovalEventKind.PENDING_SUBMITTED,
        )

        approval_time = RECORDED + timedelta(seconds=3)
        approvals._append_decision(
            PolicyApprovalCommand(
                rule_id=revision.rule_id,
                revision=revision.revision,
                revision_hash=revision.content_hash,
                kind=PolicyApprovalEventKind.APPROVED,
                actor_account_id=ACCOUNT_ID,
                reason="Approve the exact candidate revision after source review.",
                recorded_at=approval_time,
                preview_fingerprint="e" * 64,
            )
        )
        approved_request = request.model_copy(update={"as_known_at": now})
        trace = resolver.resolve_for_claims(approved_request, (claim_ref,))

        assert trace.status.value == "resolved"
        assert tuple(item.rule_id for item in trace.effective_rules) == (
            revision.rule_id,
        )
        assert trace.effective_rules[0].revision_hash == revision.content_hash
        assert trace.considered[0].evidence == (evidence,)
        assert owner.lookups == [domain_rule]

        class MemorySessions:
            saved = None

            def get(self, session_id, *, owner_scope):
                if self.saved is None or self.saved.owner_scope != owner_scope:
                    return None
                return self.saved

            def save(self, session_state, *, expected_revision=None):
                self.saved = session_state
                return session_state

            def purge_expired(self, *, now=None, limit=500):
                return 0

        assistant = AssistantService(
            MemorySessions(),  # type: ignore[arg-type]
            ConversationEngine(),
            RuleBasedDecisionPolicy(),
            RuleBasedResponsePolicy(),
            cast(AnalyticsExecutor, object()),
            cast(AdmissionFitSearchGateway, object()),
            cast(ProgramReader, object()),
            policy_resolver=resolver,
            claim_lookup=claim_repository,
            knowledge_policy_enabled=True,
        )
        result = assistant.handle(
            "Четвертый ЕГЭ меня касается? university:bmstu, поступаю в 2028 году; "
            "по состоянию на 2028-09-02.",
            owner_scope=ProfileScope(session_key_hash="f" * 64),
            now=now,
        )

        assert result.policy_answer is not None
        assert result.policy_answer.status is PolicyAnswerStatus.RESOLVED
        assert result.policy_answer.resolution_trace is not None
        assert result.policy_answer.resolution_trace.trace_id == trace.trace_id
        assert result.response is not None
        assert result.response.response_mode.value == "deterministic"
        assert result.response.knowledge is not None
        assert result.response.knowledge.resolution is not None
        assert result.response.knowledge.resolution.trace_reference == trace.trace_id
        assert result.response.knowledge.resolution.selected_rules[0].revision_hash == (
            revision.content_hash
        )
        assert result.response.knowledge.evidence[0].snapshot_sha256 == SNAPSHOT_HASH
        assert result.response.knowledge.evidence[0].locator.page == 2
        assert session.get(SourceSnapshotModel, SNAPSHOT_HASH).body == BODY
    engine.dispose()


def test_approved_source_bvi_rule_reaches_assistant_through_domain_evaluator() -> None:
    """The policy layer selects; admission_benefits remains the sole calculator."""
    from modules.admission_benefits.test_helpers import (
        PROGRAM_ID,
        olympiad_fact,
        olympiad_rule,
    )

    from andromeda.modules.admission_benefits.contracts.applicant import (
        ApplicantAdmissionFacts,
    )
    from andromeda.modules.admission_benefits.contracts.coverage import (
        AdmissionBenefitCoverage,
        AdmissionBenefitCoverageStatus,
    )
    from andromeda.modules.admission_benefits.contracts.domain_revision import (
        admission_benefit_revision_hash,
    )
    from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
        AdmissionBenefitPolicyEvaluationStatus,
        ApplicantAdmissionContext,
        ApplicantFactDimension,
    )
    from andromeda.modules.admission_benefits.contracts.provenance import (
        BenefitProvenance,
    )
    from andromeda.modules.admission_benefits.contracts.snapshot import (
        AdmissionBenefitsSnapshot,
    )
    from andromeda.modules.admission_benefits.services.policy_evaluation import (
        AdmissionBenefitsPolicyEvaluationService,
    )
    from andromeda.modules.admissions.contracts.public import ProgramAdmissions
    from andromeda.modules.conversation.contracts.assistant import (
        PolicyAnswerStatus,
    )
    from andromeda.modules.conversation.contracts.public import (
        ConversationIntent,
        QuerySession,
    )
    from andromeda.modules.entity_resolution.contracts.public import (
        ResolutionEntityType,
    )
    from andromeda.modules.policy.contracts.resolution import (
        PolicyResolutionStatus,
    )
    from andromeda.modules.programs.domain.entities import Program
    from andromeda.shared.contracts.enums import SourceKind
    from andromeda.shared.contracts.provenance import SourceAttribution

    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2028, 9, 15, tzinfo=UTC)
    evidence_source = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url=SOURCE_URL,
        captured_at=CAPTURED,
        content_sha256=SNAPSHOT_HASH,
        locator="page=2;section=BVI",
        university_id="university:bmstu",
        run_id=RUN_ID,
    )
    benefit_provenance = BenefitProvenance(
        source=evidence_source,
        source_snapshot_hash=SNAPSHOT_HASH,
        source_run_id=RUN_ID,
        admission_year=2028,
        document_title="Правила приема МГТУ 2028",
        document_kind="admission_rules",
        page=2,
        section="BVI",
        parser_version="test-parser.v1",
    )
    owner_rule = olympiad_rule().model_copy(
        update={"admission_year": 2028, "provenance": benefit_provenance}
    )
    owner_hash = admission_benefit_revision_hash(owner_rule)
    domain_rule = DomainRuleRef(
        owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
        canonical_rule_id=owner_rule.id,
        owner_revision=1,
        owner_revision_hash=owner_hash,
    )

    try:
        with Session(engine) as session:
            evidence = _source_evidence(session)
            claim_repository = SqlAlchemyKnowledgeCandidateRepository(session)
            claim = _claim(
                evidence,
                assertion="Олимпиада Шаг в будущее дает право БВИ в 2028 году.",
                predicate="admission_benefit.bvi",
                subject_kind=ClaimSubjectKind.OLYMPIAD,
                subject_id="olympiad:shag-v-budushchee",
                value=True,
                unit=None,
            )
            claim_repository.append_claim_candidate(claim)
            session.execute(
                update(KnowledgeClaimModel)
                .where(
                    KnowledgeClaimModel.claim_id == claim.claim_id,
                    KnowledgeClaimModel.revision == claim.clock.revision,
                )
                .values(review_state=ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION.value)
            )
            session.commit()

            revision = _policy_revision(evidence, claim, domain_rule=domain_rule)
            policies = SqlAlchemyPolicyRuleRepository(session)

            class Capabilities:
                @staticmethod
                def require_capability(actor_account_id, capability) -> None:
                    assert actor_account_id == ACCOUNT_ID
                    assert capability in {
                        PolicyApprovalCapability.SUBMIT_REVISION,
                        PolicyApprovalCapability.APPROVE_REVISION,
                    }

            approvals = PolicyApprovalCommandService(
                repository=policies,
                authorizer=Capabilities(),
                unit_of_work=session,
            )
            approvals.submit(
                PolicyRuleSubmission(
                    revision=revision,
                    submitted_by_account_id=ACCOUNT_ID,
                    reason="Submit the source-backed BVI candidate for review.",
                    submitted_at=RECORDED + timedelta(seconds=2),
                )
            )
            approvals._append_decision(
                PolicyApprovalCommand(
                    rule_id=revision.rule_id,
                    revision=revision.revision,
                    revision_hash=revision.content_hash,
                    kind=PolicyApprovalEventKind.APPROVED,
                    actor_account_id=ACCOUNT_ID,
                    reason="Approve the exact BVI revision after evidence review.",
                    recorded_at=RECORDED + timedelta(seconds=3),
                    preview_fingerprint="f" * 64,
                )
            )

            cycle = AdmissionCycle(
                cycle_id="admission-cycle:bmstu:2028",
                revision=1,
                university_id="university:bmstu",
                admission_year=2028,
                academic_year="2028/2029",
                application_period=InclusiveDateWindow(
                    start_date=datetime(2028, 6, 1, tzinfo=UTC).date(),
                    end_date=datetime(2028, 7, 30, tzinfo=UTC).date(),
                ),
                enrollment_period=None,
                state=AdmissionCycleState.PUBLISHED,
                evidence=(evidence,),
                approved_by_account_id=ACCOUNT_ID,
                approved_at=RECORDED + timedelta(seconds=1),
                approval_reason="Use the captured official admission calendar.",
                recorded_at=RECORDED + timedelta(seconds=1),
            )

            class Cycles(PolicyAdmissionCycleReader):
                def resolve_for_admission(
                    self, university_id, admission_year, *, as_known_at=None
                ) -> AdmissionCycleResolution:
                    if (
                        university_id != cycle.university_id
                        or admission_year != cycle.admission_year
                        or (as_known_at is not None and cycle.recorded_at > as_known_at)
                    ):
                        return AdmissionCycleResolution(
                            status=AdmissionCycleResolutionStatus.BLOCKED_BY_MISSING_DATA,
                            reason="No matching approved admission cycle is available.",
                        )
                    return AdmissionCycleResolution(
                        status=AdmissionCycleResolutionStatus.RESOLVED,
                        cycle=cycle,
                    )

            class PolicyOwner(PolicyDomainRuleReader):
                owner_module = PolicyDomainOwner.ADMISSION_BENEFITS

                def lookup_rule(self, reference: DomainRuleRef) -> PolicyDomainRuleLookup:
                    assert reference == domain_rule
                    return PolicyDomainRuleLookup(
                        requested_reference=reference,
                        resolved_reference=reference,
                        status=PolicyDomainLookupStatus.AVAILABLE,
                    )

            class Clock(PolicyClock):
                def now(self) -> datetime:
                    return now

            resolver = EffectivePolicyResolver(
                policies=policies,
                admission_cycles=Cycles(),
                domain_readers=(PolicyOwner(),),
                clock=Clock(),
            )

            class BenefitReader:
                def get_catalog(self, _university_id, _admission_year, _education_level=None):
                    return snapshot

                def get_rules_for_program(
                    self, _program_id, _admission_year, *, include_review=False, campus_id=None
                ):
                    return (owner_rule,)

                def get_individual_achievement_policy(
                    self, _university_id, _admission_year, _education_level=None,
                    *, include_review=False
                ):
                    return None

                def get_rule_revision(self, rule_id, revision_hash):
                    return owner_rule if (rule_id, revision_hash) == (owner_rule.id, owner_hash) else None

                def get_individual_achievement_policy_revision(self, _policy_id, _revision_hash):
                    return None

            class Admissions:
                def get_for_program(self, program_id):
                    return ProgramAdmissions(program_id=program_id)

            snapshot = AdmissionBenefitsSnapshot(
                university_id="university:bmstu",
                admission_year=2028,
                sources=(evidence_source,),
                benefit_rules=(owner_rule,),
                coverage=AdmissionBenefitCoverage(
                    status=AdmissionBenefitCoverageStatus.COMPLETE,
                    source_hashes=(SNAPSHOT_HASH,),
                ),
            )
            benefit_evaluator = AdmissionBenefitsPolicyEvaluationService(
                BenefitReader(), Admissions()  # type: ignore[arg-type]
            )

            class Programs:
                def get(self, program_id: str) -> Program | None:
                    if program_id != PROGRAM_ID:
                        return None
                    return Program(
                        id=PROGRAM_ID,
                        direction_id="direction:bmstu:09.03.03",
                        code="09.03.03-01",
                        name="Прикладная информатика",
                        education_year=2028,
                        study_plan_url="https://bmstu.example/plan",
                        source_url="https://bmstu.example/program",
                    )

                def list(self, _university_id=None):
                    return ()

            owner_scope = ProfileScope(session_key_hash="f" * 64)
            seeded_session = QuerySession(
                session_id="query-session:" + "e" * 32,
                owner_scope=owner_scope,
                intent=ConversationIntent.KNOWLEDGE_POLICY_QUERY,
                entities={
                    ResolutionEntityType.UNIVERSITY: ("university:bmstu",),
                    ResolutionEntityType.PROGRAM: (PROGRAM_ID,),
                },
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(hours=1),
            )

            class MemorySessions:
                saved = seeded_session

                def get(self, session_id, *, owner_scope):
                    if self.saved is None or self.saved.owner_scope != owner_scope:
                        return None
                    return self.saved

                def save(self, session_state, *, expected_revision=None):
                    self.saved = session_state
                    return session_state

                def purge_expired(self, *, now=None, limit=500):
                    return 0

            assistant = AssistantService(
                MemorySessions(),  # type: ignore[arg-type]
                ConversationEngine(),
                RuleBasedDecisionPolicy(),
                RuleBasedResponsePolicy(),
                cast(AnalyticsExecutor, object()),
                cast(AdmissionFitSearchGateway, object()),
                Programs(),  # type: ignore[arg-type]
                policy_resolver=resolver,
                claim_lookup=claim_repository,
                admission_benefit_policy_evaluator=benefit_evaluator,
                knowledge_policy_enabled=True,
            )
            result = assistant.handle(
                "БВИ влияет на мои шансы, поступаю в 2028 году; "
                "по состоянию на 2028-09-02.",
                owner_scope=owner_scope,
                session_id=seeded_session.session_id,
                applicant_admission_context=ApplicantAdmissionContext(
                    facts=ApplicantAdmissionFacts(
                        olympiad_achievements=(olympiad_fact(result_year=2026),)
                    ),
                    complete_dimensions=(ApplicantFactDimension.OLYMPIAD_ACHIEVEMENTS,),
                ),
                now=now,
            )

            assert result.policy_answer is not None
            assert result.policy_answer.status is PolicyAnswerStatus.RESOLVED
            assert result.policy_answer.resolution_trace is not None
            assert result.policy_answer.resolution_trace.status is PolicyResolutionStatus.RESOLVED
            assert result.policy_answer.domain_evaluation is not None
            assert result.policy_answer.domain_evaluation.status is (
                AdmissionBenefitPolicyEvaluationStatus.EVALUATED
            )
            decision = result.policy_answer.domain_evaluation.decision
            assert decision is not None
            assert decision.route.value == "olympiad"
            assert decision.eligibility is not None
            assert decision.eligibility.evaluations[0].status.value == "eligible"
            assert result.response is not None
            assert result.response.knowledge is not None
            assert result.response.knowledge.resolution is not None
            assert result.response.knowledge.resolution.trace_reference == (
                result.policy_answer.resolution_trace.trace_id
            )
            assert result.response.knowledge.evidence[0].snapshot_sha256 == SNAPSHOT_HASH
            assert result.response.knowledge.evidence[0].locator.page == 2
    finally:
        engine.dispose()


def test_conflict_group_round_trips_sources_and_preserves_resolution_audit_per_revision() -> (
    None
):
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            evidence = _source_evidence(session)
            candidate_repository = SqlAlchemyKnowledgeCandidateRepository(session)
            claim = _claim(evidence)
            candidate_repository.append_claim_candidate(claim)
            session.execute(
                update(KnowledgeClaimModel)
                .where(
                    KnowledgeClaimModel.claim_id == claim.claim_id,
                    KnowledgeClaimModel.revision == claim.clock.revision,
                )
                .values(review_state="accepted_as_source_assertion")
            )
            session.commit()

            class AllowPolicyCapabilities:
                @staticmethod
                def require_capability(
                    actor_account_id: str, capability: PolicyApprovalCapability
                ) -> None:
                    assert actor_account_id == ACCOUNT_ID
                    assert capability in {
                        PolicyApprovalCapability.SUBMIT_REVISION,
                        PolicyApprovalCapability.APPROVE_REVISION,
                    }

            policy_repository = SqlAlchemyPolicyRuleRepository(session)
            service = PolicyApprovalCommandService(
                repository=policy_repository,
                authorizer=AllowPolicyCapabilities(),
                unit_of_work=session,
            )
            first = _policy_revision(evidence, claim)
            second_fields = PolicyRuleRevisionFields(
                **{
                    **first.model_dump(mode="python", exclude={"content_hash"}),
                    "rule_id": "policy-rule:bmstu-competing-rule",
                }
            )
            second = create_policy_rule_revision(second_fields)
            for revision, submitted_at, decided_at in (
                (
                    first,
                    RECORDED + timedelta(seconds=2),
                    RECORDED + timedelta(seconds=3),
                ),
                (
                    second,
                    RECORDED + timedelta(seconds=4),
                    RECORDED + timedelta(seconds=5),
                ),
            ):
                service.submit(
                    PolicyRuleSubmission(
                        revision=revision,
                        submitted_by_account_id=ACCOUNT_ID,
                        reason="Submit the source-backed rule for conflict regression.",
                        submitted_at=submitted_at,
                    )
                )
                service._append_decision(
                    PolicyApprovalCommand(
                        rule_id=revision.rule_id,
                        revision=revision.revision,
                        revision_hash=revision.content_hash,
                        kind=PolicyApprovalEventKind.APPROVED,
                        actor_account_id=ACCOUNT_ID,
                        reason="Approve the exact source-backed revision for conflict regression.",
                        recorded_at=decided_at,
                        preview_fingerprint=("b" if revision is first else "c") * 64,
                    )
                )

            participants = (
                KnowledgeConflictParticipant(
                    reference=ConflictParticipantReference(
                        kind=ConflictParticipantKind.POLICY_RULE_REVISION,
                        object_id=first.rule_id,
                        revision=first.revision,
                        content_hash=first.content_hash,
                    ),
                    role=ConflictParticipantRole.COMPETING,
                    evidence=(evidence,),
                ),
                KnowledgeConflictParticipant(
                    reference=ConflictParticipantReference(
                        kind=ConflictParticipantKind.POLICY_RULE_REVISION,
                        object_id=second.rule_id,
                        revision=second.revision,
                        content_hash=second.content_hash,
                    ),
                    role=ConflictParticipantRole.COMPETING,
                    evidence=(evidence,),
                ),
            )
            scope = KnowledgeConflictScope(
                level=KnowledgeConflictScopeLevel.UNIVERSITY,
                scope_id="university:bmstu",
            )
            interval = ConflictValidInterval(start=datetime(2028, 9, 1, tzinfo=UTC))
            conflict_id = knowledge_conflict_group_id(
                KnowledgeConflictKind.POLICY_PRECEDENCE,
                scope,
                interval,
                participants,
            )
            group_fields = KnowledgeConflictGroupRevisionFields(
                conflict_id=conflict_id,
                revision=1,
                kind=KnowledgeConflictKind.POLICY_PRECEDENCE,
                scope=scope,
                valid_interval=interval,
                participants=participants,
                recorded_at=RECORDED + timedelta(seconds=6),
            )
            group = KnowledgeConflictGroupRevision(
                **group_fields.model_dump(mode="python"),
                content_hash=knowledge_conflict_content_hash(group_fields),
            )
            repository = SqlAlchemyConflictGroupRepository(session)
            repository.append_conflict_group(group)
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(
                    KnowledgeConflictParticipantModel(
                        conflict_id=conflict_id,
                        group_revision=1,
                        ordinal=2,
                        participant_kind="policy_rule_revision",
                        role="competing",
                        policy_rule_id=first.rule_id,
                        policy_revision=first.revision,
                        policy_hash=first.content_hash,
                    )
                )
                session.flush()
            opened = repository.get_conflict_group(conflict_id, 1)
            assert opened is not None
            assert repository.list_for_participant(participants[0].reference) == (
                opened,
            )
            assert opened.state is KnowledgeConflictState.OPEN
            assert opened.events[0].kind is KnowledgeConflictEventKind.OPENED
            assert len(opened.revision.participants) == 2
            assert session.query(KnowledgeConflictGroupModel).count() == 1
            assert session.query(KnowledgeConflictParticipantModel).count() == 2
            assert session.query(KnowledgeConflictEvidenceModel).count() == 2
            assert session.query(KnowledgeConflictEventModel).count() == 1

            resolved = create_knowledge_conflict_event(
                conflict_id=conflict_id,
                group_revision=1,
                group_hash=group.content_hash,
                sequence=2,
                kind=KnowledgeConflictEventKind.RESOLVED_BY_HUMAN_REVIEW,
                actor_account_id=ACCOUNT_ID,
                reason="Reviewer selected the exact approved rule participant.",
                resolution_participant=participants[0].reference,
                recorded_at=RECORDED + timedelta(seconds=7),
            )
            repository.append_conflict_event(resolved)
            historical = repository.get_conflict_group(conflict_id, 1)
            assert historical is not None
            assert repository.list_for_participant(participants[0].reference) == (
                historical,
            )
            assert historical.state is KnowledgeConflictState.RESOLVED
            assert (
                historical.events[-1].resolution_participant
                == participants[0].reference
            )

            second_revision_fields = KnowledgeConflictGroupRevisionFields(
                **{
                    **group.model_dump(mode="python", exclude={"content_hash"}),
                    "revision": 2,
                    "recorded_at": RECORDED + timedelta(seconds=8),
                }
            )
            second_group_revision = KnowledgeConflictGroupRevision(
                **second_revision_fields.model_dump(mode="python"),
                content_hash=knowledge_conflict_content_hash(second_revision_fields),
            )
            repository.append_conflict_group(second_group_revision)
            preserved = repository.get_conflict_group(conflict_id, 1)
            latest = repository.get_conflict_group(conflict_id, 2)
            assert (
                preserved is not None
                and preserved.state is KnowledgeConflictState.RESOLVED
            )
            assert len(preserved.events) == 2
            assert latest is not None and latest.state is KnowledgeConflictState.OPEN
            assert latest.revision.content_hash == second_group_revision.content_hash
    finally:
        engine.dispose()


def test_candidate_repository_persists_claims_as_known_at_and_proposal_events() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            evidence = _source_evidence(session)
            repository = SqlAlchemyKnowledgeCandidateRepository(session)
            claim = _claim(evidence)

            assert (
                repository.get_as_known_at(
                    claim.claim_id, RECORDED - timedelta(seconds=1)
                )
                is None
            )
            assert repository.append_claim_candidate(claim) == claim
            assert repository.append_claim_candidate(claim) == claim
            assert repository.get_claim_revision(claim.claim_id, 1) == claim
            assert repository.get_as_known_at(claim.claim_id, RECORDED) == claim
            assert repository.list_for_observation(evidence.source_observation_id) == (
                claim,
            )
            assert repository.list_pending_claims() == (claim,)

            claim_ref = ClaimRevisionRef(claim_id=claim.claim_id, revision=1)
            event = ChangeEvent(
                change_event_id=change_event_id_for_claims(
                    ChangeEventKind.PROPOSAL_PUBLISHED, (claim_ref,)
                ),
                clock=BitemporalRevision(
                    revision=1, recorded_at=RECORDED + timedelta(seconds=1)
                ),
                primary_source_observation_id=evidence.source_observation_id,
                event_kind=ChangeEventKind.PROPOSAL_PUBLISHED,
                source_milestones=SourceMilestones(
                    published_at=CAPTURED,
                    captured_at=CAPTURED,
                ),
                claims=(claim_ref,),
                evidence=(evidence,),
            )
            assert repository.append_change_event_candidate(event) == event
            assert repository.append_change_event_candidate(event) == event
            assert (
                repository.get_change_event_revision(event.change_event_id, 1) == event
            )
            assert repository.list_pending_change_events() == (event,)
            assert session.query(KnowledgeClaimModel).count() == 1
            assert session.query(KnowledgeClaimEvidenceModel).count() == 1
            assert session.query(KnowledgeChangeEventModel).count() == 1
    finally:
        engine.dispose()


def test_claim_lookup_is_predicate_bounded_temporal_and_source_attributed() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            evidence = _source_evidence(session)
            repository = SqlAlchemyKnowledgeCandidateRepository(session)
            first = _claim(evidence)
            repository.append_claim_candidate(first)

            first_snapshot = repository.list_by_predicate(
                "admission.minimum_ege_score",
                as_known_at=RECORDED,
            )
            assert len(first_snapshot) == 1
            assert first_snapshot[0].claim == first
            assert first_snapshot[0].source_display_name == "Official Ministry proposal"
            assert (
                first_snapshot[0].source_kind
                is KnowledgeSourceKind.MINISTRY_PUBLICATION
            )
            assert (
                first_snapshot[0].source_reliability
                is SourceReliabilityTier.OFFICIAL_ISSUER
            )
            assert (
                repository.list_by_predicate(
                    "admission.unregistered_predicate",
                    as_known_at=RECORDED,
                )
                == ()
            )

            second = first.model_copy(
                update={
                    "clock": first.clock.model_copy(
                        update={
                            "revision": 2,
                            "recorded_at": RECORDED + timedelta(seconds=2),
                        }
                    ),
                    "review_state": ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION,
                }
            )
            repository.append_reviewed_claim_revision(second)

            assert (
                repository.list_by_predicate(
                    "admission.minimum_ege_score",
                    as_known_at=RECORDED,
                )[0].claim.clock.revision
                == 1
            )
            latest = repository.list_by_predicate(
                "admission.minimum_ege_score",
                as_known_at=RECORDED + timedelta(seconds=3),
            )
            assert len(latest) == 1
            assert latest[0].claim.clock.revision == 2
            assert (
                latest[0].claim.review_state
                is ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION
            )
    finally:
        engine.dispose()


def test_exact_duplicate_claim_candidates_cluster_without_merging_evidence() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            first_evidence = _source_evidence(session)
            second_evidence = _secondary_source_evidence(session)
            repository = SqlAlchemyKnowledgeCandidateRepository(session)
            first = _claim(first_evidence)
            second = _claim(second_evidence)

            assert first.claim_id != second.claim_id
            assert fingerprint_claim(first) == fingerprint_claim(second)
            repository.append_claim_candidate(first)
            repository.append_claim_candidate(first)
            assert session.query(KnowledgeClaimCandidateClusterModel).count() == 1
            repository.append_claim_candidate(second)

            cluster = repository.get_exact_claim_cluster(fingerprint_claim(first))
            assert isinstance(cluster, ClaimCandidateCluster)
            assert len(cluster.members) == 2
            assert {member.claim_id for member in cluster.members} == {
                first.claim_id,
                second.claim_id,
            }
            assert cluster.cluster_id.startswith("claim-cluster:")
            assert session.query(KnowledgeClaimModel).count() == 2
            assert session.query(KnowledgeClaimEvidenceModel).count() == 2
            clusters = session.query(KnowledgeClaimCandidateClusterModel).all()
            assert len(clusters) == 1, [
                (item.cluster_id, item.fingerprint, item.fingerprint_version)
                for item in clusters
            ]
            assert session.query(KnowledgeClaimCandidateClusterMemberModel).count() == 2
    finally:
        engine.dispose()


def test_policy_revision_and_pending_event_are_atomic_and_exact_hash_approval_is_terminal() -> (
    None
):
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            evidence = _source_evidence(session)
            candidate_repository = SqlAlchemyKnowledgeCandidateRepository(session)
            claim = _claim(evidence)
            candidate_repository.append_claim_candidate(claim)
            session.commit()

            revision = _policy_revision(evidence, claim)
            policy_repository = SqlAlchemyPolicyRuleRepository(session)

            class AllowPolicyCapabilities:
                @staticmethod
                def require_capability(
                    actor_account_id: str, capability: PolicyApprovalCapability
                ) -> None:
                    assert actor_account_id in {ACCOUNT_ID, "account:" + "e" * 32}
                    assert capability in {
                        PolicyApprovalCapability.SUBMIT_REVISION,
                        PolicyApprovalCapability.APPROVE_REVISION,
                    }

            service = PolicyApprovalCommandService(
                repository=policy_repository,
                authorizer=AllowPolicyCapabilities(),
                unit_of_work=session,
            )
            submission = PolicyRuleSubmission(
                revision=revision,
                submitted_by_account_id=ACCOUNT_ID,
                reason="Submit source-backed future revision for explicit approval.",
                submitted_at=RECORDED + timedelta(seconds=2),
            )

            with pytest.raises(ValidationError, match="accepted source assertions"):
                service.submit(submission)
            assert session.query(PolicyRuleRevisionModel).count() == 0
            assert session.query(PolicyApprovalEventModel).count() == 0

            session.execute(
                update(KnowledgeClaimModel)
                .where(
                    KnowledgeClaimModel.claim_id == claim.claim_id,
                    KnowledgeClaimModel.revision == claim.clock.revision,
                )
                .values(review_state="accepted_as_source_assertion")
            )
            session.commit()

            pending = service.submit(submission)
            assert pending.kind is PolicyApprovalEventKind.PENDING_SUBMITTED
            assert pending.revision_hash == revision.content_hash
            assert (
                derive_approval_state(
                    policy_repository.list_approval_events(
                        revision.rule_id, revision.revision
                    ),
                    rule_id=revision.rule_id,
                    revision=revision.revision,
                    revision_hash=revision.content_hash,
                )
                is PolicyApprovalState.PENDING
            )
            assert (
                policy_repository.get_revision(revision.rule_id, revision.revision)
                == revision
            )
            assert policy_repository.list_pending_revisions() == (revision,)
            assert (
                policy_repository.get_approved_revision(
                    revision.rule_id, revision.revision
                )
                is None
            )
            assert (
                policy_repository.list_approved_revisions(
                    as_known_at=RECORDED + timedelta(seconds=2)
                )
                == ()
            )
            assert session.query(PolicyRuleRevisionModel).count() == 1
            assert session.query(PolicyApprovalEventModel).count() == 1

            reviewer_id = "account:" + "e" * 32
            session.add(
                AccountModel(
                    account_id=reviewer_id,
                    email="policy-reviewer@example.test",
                    password_hash="test-hash",
                    created_at=CAPTURED,
                    updated_at=CAPTURED,
                )
            )
            session.flush()
            session.commit()
            approval_command = PolicyApprovalCommand(
                rule_id=revision.rule_id,
                revision=revision.revision,
                revision_hash=revision.content_hash,
                kind=PolicyApprovalEventKind.APPROVED,
                actor_account_id=reviewer_id,
                reason="Reviewed exact content and source evidence.",
                recorded_at=RECORDED + timedelta(seconds=3),
                preview_fingerprint="d" * 64,
            )
            with pytest.raises(ValidationError, match="reviewed preview gate"):
                service.decide(approval_command)
            approval = service._append_decision(approval_command)
            assert service._append_decision(approval_command) == approval
            assert approval.sequence == 2
            assert approval.preview_fingerprint == "d" * 64
            events = policy_repository.list_approval_events(
                revision.rule_id, revision.revision
            )
            assert events[-1].preview_fingerprint == "d" * 64
            assert (
                derive_approval_state(
                    events,
                    rule_id=revision.rule_id,
                    revision=revision.revision,
                    revision_hash=revision.content_hash,
                )
                is PolicyApprovalState.APPROVED
            )
            assert (
                policy_repository.get_approved_revision(
                    revision.rule_id, revision.revision
                )
                == revision
            )
            assert policy_repository.list_pending_revisions() == ()
            assert policy_repository.list_approved_revisions(
                as_known_at=RECORDED + timedelta(seconds=3)
            ) == (revision,)
            approved_record = policy_repository.list_approved_revision_records(
                as_known_at=RECORDED + timedelta(seconds=3)
            )[0]
            assert approved_record.revision == revision
            assert approved_record.approval_event == approval
            with pytest.raises(
                ConflictError, match="Only a valid pending policy revision"
            ):
                service.decide(
                    PolicyApprovalCommand(
                        rule_id=revision.rule_id,
                        revision=revision.revision,
                        revision_hash=revision.content_hash,
                        kind=PolicyApprovalEventKind.REJECTED,
                        actor_account_id=reviewer_id,
                        reason="A terminal approved revision cannot be rejected.",
                        recorded_at=RECORDED + timedelta(seconds=4),
                    )
                )
            assert session.query(PolicyApprovalEventModel).count() == 2
    finally:
        engine.dispose()


def test_approved_policy_revision_scan_batches_approval_and_provenance_reads() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            evidence = _source_evidence(session)
            candidate_repository = SqlAlchemyKnowledgeCandidateRepository(session)
            claim = _claim(evidence)
            candidate_repository.append_claim_candidate(claim)
            session.execute(
                update(KnowledgeClaimModel)
                .where(
                    KnowledgeClaimModel.claim_id == claim.claim_id,
                    KnowledgeClaimModel.revision == claim.clock.revision,
                )
                .values(review_state="accepted_as_source_assertion")
            )
            session.commit()

            policy_repository = SqlAlchemyPolicyRuleRepository(session)

            class AllowPolicyCapabilities:
                @staticmethod
                def require_capability(
                    actor_account_id: str, capability: PolicyApprovalCapability
                ) -> None:
                    assert actor_account_id == ACCOUNT_ID
                    assert capability in {
                        PolicyApprovalCapability.SUBMIT_REVISION,
                        PolicyApprovalCapability.APPROVE_REVISION,
                    }

            service = PolicyApprovalCommandService(
                repository=policy_repository,
                authorizer=AllowPolicyCapabilities(),
                unit_of_work=session,
            )
            base = _policy_revision(evidence, claim)
            revisions = tuple(
                create_policy_rule_revision(
                    PolicyRuleRevisionFields(
                        rule_id=f"policy-rule:query-budget-{index}",
                        revision=1,
                        schema_version=base.schema_version,
                        family_id=base.family_id,
                        authority=base.authority,
                        selector=base.selector,
                        scope=base.scope,
                        domain_rule=base.domain_rule,
                        lifecycle=base.lifecycle,
                        temporal=base.temporal,
                        source_claims=base.source_claims,
                        evidence=base.evidence,
                    )
                )
                for index in range(3)
            )
            for revision in revisions:
                service.submit(
                    PolicyRuleSubmission(
                        revision=revision,
                        submitted_by_account_id=ACCOUNT_ID,
                        reason="Submit exact source-backed policy for query-budget test.",
                        submitted_at=RECORDED + timedelta(seconds=2),
                    )
                )
                service._append_decision(
                    PolicyApprovalCommand(
                        rule_id=revision.rule_id,
                        revision=revision.revision,
                        revision_hash=revision.content_hash,
                        kind=PolicyApprovalEventKind.APPROVED,
                        actor_account_id=ACCOUNT_ID,
                        reason="Approve exact source-backed policy for query-budget test.",
                        recorded_at=RECORDED + timedelta(seconds=3),
                        preview_fingerprint="f" * 64,
                    )
                )
            session.commit()

            select_statements: list[str] = []

            def record_select(_connection, _cursor, statement, *_args) -> None:
                if statement.lstrip().upper().startswith("SELECT"):
                    select_statements.append(statement)

            event.listen(engine, "before_cursor_execute", record_select)
            try:
                approved = policy_repository.list_approved_revisions(
                    as_known_at=RECORDED + timedelta(seconds=4)
                )
            finally:
                event.remove(engine, "before_cursor_execute", record_select)

            assert len(approved) == 3
            assert {item.rule_id for item in approved} == {
                item.rule_id for item in revisions
            }
            assert len(select_statements) == 6
    finally:
        engine.dispose()


def test_candidate_repository_rejects_reviewed_or_untrusted_candidate_writes() -> None:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            evidence = _source_evidence(session)
            repository = SqlAlchemyKnowledgeCandidateRepository(session)
            accepted = _claim(evidence).model_copy(
                update={"review_state": "accepted_as_source_assertion"}
            )
            with pytest.raises(ValidationError, match="only accepts unreviewed claims"):
                repository.append_claim_candidate(accepted)

            unsafe = _claim(evidence).model_copy(
                update={
                    "evidence": (
                        ClaimEvidenceLink(
                            relationship=ClaimEvidenceRelationship.ORIGINATES_FROM,
                            evidence=evidence.model_copy(
                                update={
                                    "source_url": "https://unlisted.example/fake.pdf"
                                }
                            ),
                        ),
                    )
                }
            )
            with pytest.raises(
                ValidationError, match="outside its approved source allowlist"
            ):
                repository.append_claim_candidate(unsafe)
    finally:
        engine.dispose()


def test_typed_claim_relations_are_exact_source_backed_and_derived_from_cycles_fail_closed() -> (
    None
):
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            evidence = _source_evidence(session)
            candidates = SqlAlchemyKnowledgeCandidateRepository(session)
            first = _claim(evidence)
            second = _claim(
                evidence,
                recorded_at=RECORDED + timedelta(seconds=1),
                assertion="The same source also describes an 80 point minimum score.",
                start_offset=240,
            )
            candidates.append_claim_candidate(first)
            candidates.append_claim_candidate(second)
            repository = SqlAlchemyKnowledgeRelationRepository(session)

            fields = KnowledgeClaimRelationRevisionFields(
                relation_id=knowledge_relation_id(
                    KnowledgeRelationKind.SUPPORTED_BY,
                    ClaimRevisionRef(
                        claim_id=first.claim_id, revision=first.clock.revision
                    ),
                    ClaimRevisionRef(
                        claim_id=second.claim_id, revision=second.clock.revision
                    ),
                ),
                revision=1,
                kind=KnowledgeRelationKind.SUPPORTED_BY,
                source=ClaimRevisionRef(
                    claim_id=first.claim_id, revision=first.clock.revision
                ),
                target=ClaimRevisionRef(
                    claim_id=second.claim_id, revision=second.clock.revision
                ),
                valid_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
                review_state=KnowledgeRelationReviewState.CANDIDATE,
                evidence=(evidence,),
                recorded_at=RECORDED + timedelta(seconds=2),
            )
            relation = KnowledgeClaimRelationRevision(
                **fields.model_dump(mode="python"),
                content_hash=knowledge_relation_content_hash(fields),
            )
            repository.append_relation(relation)
            assert repository.get_relation(relation.relation_id, 1) == relation
            assert repository.list_relations(first.claim_id, approved_only=False) == (
                relation,
            )
            assert repository.list_relations(first.claim_id) == ()

            derived_fields = KnowledgeClaimRelationRevisionFields(
                relation_id=knowledge_relation_id(
                    KnowledgeRelationKind.DERIVED_FROM,
                    ClaimRevisionRef(
                        claim_id=first.claim_id, revision=first.clock.revision
                    ),
                    ClaimRevisionRef(
                        claim_id=second.claim_id, revision=second.clock.revision
                    ),
                ),
                revision=1,
                kind=KnowledgeRelationKind.DERIVED_FROM,
                source=ClaimRevisionRef(
                    claim_id=first.claim_id, revision=first.clock.revision
                ),
                target=ClaimRevisionRef(
                    claim_id=second.claim_id, revision=second.clock.revision
                ),
                review_state=KnowledgeRelationReviewState.CANDIDATE,
                evidence=(evidence,),
                recorded_at=RECORDED + timedelta(seconds=3),
            )
            derived = KnowledgeClaimRelationRevision(
                **derived_fields.model_dump(mode="python"),
                content_hash=knowledge_relation_content_hash(derived_fields),
            )
            repository.append_relation(derived)

            cycle_fields = KnowledgeClaimRelationRevisionFields(
                relation_id=knowledge_relation_id(
                    KnowledgeRelationKind.DERIVED_FROM,
                    ClaimRevisionRef(
                        claim_id=second.claim_id, revision=second.clock.revision
                    ),
                    ClaimRevisionRef(
                        claim_id=first.claim_id, revision=first.clock.revision
                    ),
                ),
                revision=1,
                kind=KnowledgeRelationKind.DERIVED_FROM,
                source=ClaimRevisionRef(
                    claim_id=second.claim_id, revision=second.clock.revision
                ),
                target=ClaimRevisionRef(
                    claim_id=first.claim_id, revision=first.clock.revision
                ),
                review_state=KnowledgeRelationReviewState.CANDIDATE,
                evidence=(evidence,),
                recorded_at=RECORDED + timedelta(seconds=4),
            )
            cycle = KnowledgeClaimRelationRevision(
                **cycle_fields.model_dump(mode="python"),
                content_hash=knowledge_relation_content_hash(cycle_fields),
            )
            with pytest.raises(ValidationError, match="directed cycle"):
                repository.append_relation(cycle)
    finally:
        engine.dispose()
