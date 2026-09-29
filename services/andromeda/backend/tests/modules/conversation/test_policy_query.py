from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
    AdmissionBenefitPolicyEvaluation,
    AdmissionBenefitPolicyEvaluationRequest,
    AdmissionBenefitPolicyEvaluationStatus,
    ApplicantAdmissionContext,
)
from andromeda.modules.admission_fit.contracts.public import AdmissionFitSearchGateway
from andromeda.modules.analytics.services.executor import AnalyticsExecutor
from andromeda.modules.conversation.contracts.assistant import PolicyAnswerStatus
from andromeda.modules.conversation.contracts.public import QuerySession
from andromeda.modules.conversation.services.assistant import AssistantService
from andromeda.modules.conversation.services.engine import ConversationEngine
from andromeda.modules.conversation.services.rule_decision_policy import (
    RuleBasedDecisionPolicy,
)
from andromeda.modules.entity_resolution.contracts.public import ResolutionEntityType
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
    KnowledgeClaimLookup,
    KnowledgeSourceKind,
    SourceMilestones,
    SourceReliabilityTier,
    claim_id_for_source_assertion,
)
from andromeda.modules.policy.contracts.public import DomainRuleRef, PolicyDomainOwner
from andromeda.modules.policy.contracts.resolution import ResolutionTrace
from andromeda.modules.presentation.services.rule_response_policy import (
    RuleBasedResponsePolicy,
)
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.programs.repository.ports import ProgramReader

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
OBSERVATION_ID = "source-observation:" + "d" * 32


def _claim_lookup() -> KnowledgeClaimLookup:
    text = "Официально опубликован проект о возможном четвёртом ЕГЭ с 2028 года."
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    evidence = EvidenceRef(
        source_id="source:ministry-admission",
        source_observation_id=OBSERVATION_ID,
        snapshot_sha256="a" * 64,
        source_url="https://ministry.example/proposal.pdf",
        locator=EvidenceLocator(page=2, section="Проект правил"),
    )
    captured_at = NOW - timedelta(days=2)
    claim = Claim(
        claim_id=claim_id_for_source_assertion(
            OBSERVATION_ID,
            0,
            len(text),
            text_hash,
        ),
        clock=BitemporalRevision(
            revision=1,
            recorded_at=NOW - timedelta(days=1),
        ),
        source_observation_id=OBSERVATION_ID,
        text_start_offset=0,
        text_end_offset=len(text),
        assertion_text=text,
        assertion_text_sha256=text_hash,
        proposition=ClaimProposition(
            predicate="admission.exam.required_count",
            subject_kind=ClaimSubjectKind.EXAM,
            subject_id="exam:ege",
            value=ClaimValueDecimal(kind="decimal", value=Decimal(4)),
            unit="exam_count",
        ),
        claimed_stage=ClaimedPolicyStage.PROPOSAL,
        review_state=ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION,
        source_milestones=SourceMilestones(
            published_at=captured_at,
            captured_at=captured_at,
        ),
        extraction_method=ClaimExtractionMethod.MANUAL,
        extractor_id="human_review",
        extractor_version="v1",
        evidence=(
            ClaimEvidenceLink(
                relationship=ClaimEvidenceRelationship.ORIGINATES_FROM,
                evidence=evidence,
            ),
        ),
    )
    return KnowledgeClaimLookup(
        claim=claim,
        source_display_name="Министерство",
        source_kind=KnowledgeSourceKind.MINISTRY_PUBLICATION,
        source_reliability=SourceReliabilityTier.OFFICIAL_ISSUER,
    )


class _MemorySessionRepository:
    def __init__(self) -> None:
        self.saved: QuerySession | None = None

    def get(
        self, _session_id: str, *, owner_scope: ProfileScope
    ) -> QuerySession | None:
        if self.saved is None or self.saved.owner_scope != owner_scope:
            return None
        return self.saved

    def save(
        self,
        session: QuerySession,
        *,
        expected_revision: int | None = None,
    ) -> QuerySession:
        if expected_revision is not None and self.saved is not None:
            assert self.saved.revision == expected_revision
        self.saved = session
        return session

    def purge_expired(self, *, now: datetime | None = None, limit: int = 500) -> int:
        del now, limit
        return 0


class _ClaimLookup:
    def list_by_predicate(
        self, predicate: str, **_kwargs: object
    ) -> tuple[KnowledgeClaimLookup, ...]:
        return (
            (_claim_lookup(),) if predicate == "admission.exam.required_count" else ()
        )


def test_assistant_returns_claim_stage_and_source_reliability_separately() -> None:
    sessions = _MemorySessionRepository()
    applicant_context = ApplicantAdmissionContext()
    service = AssistantService(
        sessions,
        ConversationEngine(),
        RuleBasedDecisionPolicy(),
        RuleBasedResponsePolicy(),
        cast(AnalyticsExecutor, object()),
        cast(AdmissionFitSearchGateway, object()),
        cast(ProgramReader, object()),
        claim_lookup=_ClaimLookup(),  # type: ignore[arg-type]
        knowledge_policy_enabled=True,
    )

    result = service.handle(
        "Правда ли, что с 2028 года введут четвертый ЕГЭ?",
        owner_scope=ProfileScope(session_key_hash="f" * 64),
        applicant_admission_context=applicant_context,
        now=NOW,
    )

    assert result.policy_answer is not None
    assert result.policy_answer.status is PolicyAnswerStatus.SOURCE_ASSERTIONS_FOUND
    assert len(result.policy_answer.source_claims) == 1
    claim = result.policy_answer.source_claims[0].claim
    assert claim.claimed_stage is ClaimedPolicyStage.PROPOSAL
    assert claim.review_state is ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION
    source = result.policy_answer.source_claims[0]
    assert source.source_reliability is SourceReliabilityTier.OFFICIAL_ISSUER
    assert source.source_kind is KnowledgeSourceKind.MINISTRY_PUBLICATION
    assert result.policy_answer.resolution_trace is None
    assert result.response is not None
    assert result.response.knowledge is not None
    assert "не подтверждает действующее правило" in result.response.text
    assert result.response.knowledge.status.value == "source_assertion"
    assertion = result.response.knowledge.source_assertions[0]
    assert assertion.stage.value == "proposal"
    assert assertion.reliability.value == "official"
    assert assertion.asserted_value is not None
    assert assertion.asserted_value.value == "4"
    assert result.response.knowledge.evidence[0].source_name == "Министерство"
    assert sessions.saved is not None
    assert sessions.saved.applicant_admission_context == applicant_context
    assert "policy_answer" not in result.model_dump(mode="json")


def test_assistant_impact_bridge_forwards_only_exact_benefit_refs_and_typed_facts() -> (
    None
):
    class Programs:
        def get(self, program_id: str) -> Program | None:
            if program_id != "program:bmstu:09.03.03-01":
                return None
            return Program(
                id=program_id,
                direction_id="direction:bmstu:09.03.03",
                code="09.03.03-01",
                name="Прикладная информатика",
                education_year=2026,
                study_plan_url="https://bmstu.example/plan",
                source_url="https://bmstu.example/program",
            )

        def list(self, _university_id=None):
            return ()

    class Evaluator:
        request: AdmissionBenefitPolicyEvaluationRequest | None = None

        def evaluate(self, request: AdmissionBenefitPolicyEvaluationRequest):
            self.request = request
            return AdmissionBenefitPolicyEvaluation(
                status=AdmissionBenefitPolicyEvaluationStatus.INSUFFICIENT_DATA,
                missing_input_codes=(
                    "applicant_olympiad_achievements_completeness_unconfirmed",
                ),
            )

    evaluator = Evaluator()
    service = AssistantService(
        _MemorySessionRepository(),
        ConversationEngine(),
        RuleBasedDecisionPolicy(),
        RuleBasedResponsePolicy(),
        cast(AnalyticsExecutor, object()),
        cast(AdmissionFitSearchGateway, object()),
        Programs(),  # type: ignore[arg-type]
        admission_benefit_policy_evaluator=evaluator,  # type: ignore[arg-type]
    )
    domain_reference = DomainRuleRef(
        owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
        canonical_rule_id="admission-benefit:bmstu-bvi",
        owner_revision=3,
        owner_revision_hash="c" * 64,
    )
    trace = cast(
        ResolutionTrace,
        type(
            "Trace",
            (),
            {
                "university_id": "university:bmstu",
                "admission_year": 2026,
                "trace_id": "policy-resolution-trace:" + "a" * 32,
                "effective_rules": (
                    type("Selection", (), {"domain_rule": domain_reference})(),
                ),
            },
        )(),
    )
    session = QuerySession(
        session_id="query-session:" + "b" * 32,
        owner_scope=ProfileScope(session_key_hash="f" * 64),
        entities={ResolutionEntityType.PROGRAM: ("program:bmstu:09.03.03-01",)},
        applicant_admission_context=ApplicantAdmissionContext(),
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    result = service._evaluate_admission_benefit_impact(session, trace)

    assert result.status is AdmissionBenefitPolicyEvaluationStatus.INSUFFICIENT_DATA
    assert evaluator.request is not None
    assert evaluator.request.selected_rules[0].rule_id == "admission-benefit:bmstu-bvi"
    assert evaluator.request.selected_rules[0].revision_hash == "c" * 64
    assert evaluator.request.university_id == "university:bmstu"
    assert evaluator.request.admission_year == 2026
    assert evaluator.request.program_id == "program:bmstu:09.03.03-01"
    assert evaluator.request.applicant == session.applicant_admission_context


def test_policy_assistant_disabled_returns_outside_coverage_without_lookup() -> None:
    class _LookupMustNotRun:
        def list_by_predicate(self, *_args: object, **_kwargs: object):
            raise AssertionError("disabled policy assistant must not read claims")

    service = AssistantService(
        _MemorySessionRepository(),
        ConversationEngine(),
        RuleBasedDecisionPolicy(),
        RuleBasedResponsePolicy(),
        cast(AnalyticsExecutor, object()),
        cast(AdmissionFitSearchGateway, object()),
        cast(ProgramReader, object()),
        claim_lookup=_LookupMustNotRun(),  # type: ignore[arg-type]
    )

    result = service.handle(
        "Правда ли, что с 2028 года введут четвертый ЕГЭ?",
        owner_scope=ProfileScope(session_key_hash="f" * 64),
        now=NOW,
    )

    assert result.policy_answer is not None
    assert result.policy_answer.status is PolicyAnswerStatus.OUTSIDE_COVERAGE
    assert result.policy_answer.reason_code == "knowledge_policy_assistant_disabled"
    assert not result.policy_answer.source_claims


def test_assistant_historical_query_preserves_knowledge_time_cutoff() -> None:
    service = AssistantService(
        _MemorySessionRepository(),
        ConversationEngine(),
        RuleBasedDecisionPolicy(),
        RuleBasedResponsePolicy(),
        cast(AnalyticsExecutor, object()),
        cast(AdmissionFitSearchGateway, object()),
        cast(ProgramReader, object()),
        claim_lookup=_ClaimLookup(),  # type: ignore[arg-type]
        knowledge_policy_enabled=True,
    )
    cutoff = datetime(2026, 9, 25, 23, 59, 59, 999999, tzinfo=UTC)

    result = service.handle(
        "Что знала Andromeda на дату 2026-09-25 о четвертом ЕГЭ?",
        owner_scope=ProfileScope(session_key_hash="e" * 64),
        now=NOW,
    )

    assert result.policy_answer is not None
    assert result.policy_answer.source_claims
    assert result.response is not None and result.response.knowledge is not None
    assert result.response.knowledge.as_known_at == cutoff
    assert result.response.knowledge.source_assertions[0].stage.value == "proposal"


def test_assistant_relative_yesterday_uses_utc_day_end_as_knowledge_cutoff() -> None:
    service = AssistantService(
        _MemorySessionRepository(),
        ConversationEngine(),
        RuleBasedDecisionPolicy(),
        RuleBasedResponsePolicy(),
        cast(AnalyticsExecutor, object()),
        cast(AdmissionFitSearchGateway, object()),
        cast(ProgramReader, object()),
        claim_lookup=_ClaimLookup(),  # type: ignore[arg-type]
        knowledge_policy_enabled=True,
    )

    result = service.handle(
        "Что знала Andromeda вчера о четвертом ЕГЭ?",
        owner_scope=ProfileScope(session_key_hash="d" * 64),
        now=NOW,
    )

    assert result.response is not None and result.response.knowledge is not None
    assert result.response.knowledge.as_known_at == datetime(
        2026, 9, 25, 23, 59, 59, 999999, tzinfo=UTC
    )


def test_assistant_marks_missing_historical_snapshot_as_unavailable() -> None:
    class EmptyHistoricalClaimLookup:
        def list_by_predicate(self, predicate: str, **kwargs: object):
            del predicate, kwargs
            return ()

    service = AssistantService(
        _MemorySessionRepository(),
        ConversationEngine(),
        RuleBasedDecisionPolicy(),
        RuleBasedResponsePolicy(),
        cast(AnalyticsExecutor, object()),
        cast(AdmissionFitSearchGateway, object()),
        cast(ProgramReader, object()),
        claim_lookup=EmptyHistoricalClaimLookup(),  # type: ignore[arg-type]
        knowledge_policy_enabled=True,
    )

    result = service.handle(
        "Что знала Andromeda на дату 2025-09-01 о четвертом ЕГЭ?",
        owner_scope=ProfileScope(session_key_hash="c" * 64),
        now=NOW,
    )

    assert result.policy_answer is not None
    assert (
        result.policy_answer.status is PolicyAnswerStatus.HISTORICAL_STATE_UNAVAILABLE
    )
    assert result.response is not None and result.response.knowledge is not None
    assert result.response.knowledge.status.value == "historical_state_unavailable"
    assert "не сохранено" in result.response.text
