from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import (
    AdmissionBenefitIngestionCoverageModel,
    AdmissionBenefitRuleModel,
    DirectionModel,
    EducationalProgramModel,
    EducationLevelModel,
    IngestRunModel,
    SourceSnapshotModel,
    UniversityModel,
)
from andromeda.infrastructure.repositories.admission_benefit_policy import (
    AdmissionBenefitsPolicyRuleReader,
)
from andromeda.infrastructure.repositories.admission_benefits import (
    SqlAlchemyAdmissionBenefitsRepository,
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
    individual_achievement_domain_rule_id,
)
from andromeda.modules.admission_benefits.contracts.policy import (
    BenefitScope,
    BenefitScopeMode,
    BenefitTarget,
    BenefitTargetKind,
)
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.public import (
    AchievementCombinationPolicy,
    AdmissionBenefitRule,
    AdmissionRoute,
    BenefitType,
    ConfirmationApplicantCategory,
    ConfirmationExamKind,
    ConfirmationRequirement,
    ConfirmationSubjectRule,
    IndividualAchievementPolicy,
    IndividualAchievementRule,
    Olympiad,
    OlympiadProfile,
    OlympiadProfileSubject,
    OlympiadResultType,
    ValidityPolicy,
)
from andromeda.modules.admission_benefits.contracts.results import EligibilityStatus
from andromeda.modules.admission_benefits.contracts.snapshot import (
    AdmissionBenefitsSnapshot,
)
from andromeda.modules.admission_benefits.contracts.status import (
    BenefitPolicyVersion,
    RuleDataStatus,
    TargetResolutionStatus,
)
from andromeda.modules.admission_benefits.repository.ports import AdmissionBenefitReader
from andromeda.modules.admission_benefits.services.admission_decision import (
    AdmissionDecisionService,
)
from andromeda.modules.admission_benefits.services.evaluator import (
    AdmissionBenefitEvaluationInput,
)
from andromeda.modules.admission_benefits.services.facade import (
    AdmissionEligibilityService,
)
from andromeda.modules.admissions.contracts.admission_cycles import (
    AdmissionCycle,
    AdmissionCycleResolution,
    AdmissionCycleResolutionStatus,
    AdmissionCycleState,
    InclusiveDateWindow,
)
from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    ClaimRevisionRef,
    EvidenceLocator,
    EvidenceRef,
    SourceMilestones,
    TemporalInterval,
)
from andromeda.modules.knowledge.repository.ports import SourceObservationRepository
from andromeda.modules.policy.contracts.applicability import (
    PolicyDomainLookupStatus,
)
from andromeda.modules.policy.contracts.approval import (
    ApprovedPolicyRevision,
    PolicyApprovalEventKind,
)
from andromeda.modules.policy.contracts.impact import (
    DomainImpactStatus,
    ImpactActionability,
    PolicyImpactContext,
)
from andromeda.modules.policy.contracts.resolution import PolicyResolutionRequest
from andromeda.modules.policy.contracts.rule import (
    DomainRuleRef,
    PolicyAuthorityLevel,
    PolicyDomainOwner,
    PolicyRevisionLifecycle,
    PolicyRuleRevision,
    PolicyRuleRevisionFields,
    PolicyScope,
    PolicyScopeLevel,
    policy_rule_content_hash,
)
from andromeda.modules.policy.contracts.rule_ast import (
    PolicyContextField,
    PolicySelectorAst,
    PolicySelectorNode,
    PolicySelectorNodeKind,
)
from andromeda.modules.policy.contracts.temporal import PolicyTemporalRevision
from andromeda.modules.policy.domain.approval import create_approval_event
from andromeda.modules.policy.repository.ports import ApprovedPolicyRuleReader
from andromeda.modules.policy.services.effective_rule_resolver import (
    EffectivePolicyResolver,
)
from andromeda.modules.policy.services.ports import (
    PolicyAdmissionCycleReader,
    PolicyClock,
)
from andromeda.shared.contracts.enums import EducationLevel, SourceKind
from andromeda.shared.contracts.ids import SourceHash
from andromeda.shared.contracts.provenance import (
    GapSeverity,
    SourceAttribution,
    SourceGapReference,
)

RUN_ID = "ingest:" + "a" * 32
SOURCE_URL = "https://api.www.bmstu.ru/file/122150/download"
SOURCE_HASH = "b" * 64
MANIFEST_HASH = "e" * 64
PROGRAM_ID = "program:bmstu:09.03.03-01"
UNIVERSITY_ID = "university:bmstu"
INDEX_URL = "https://api.www.bmstu.ru/page/admission-committee-documents"


def _provenance(*, row: int = 1, source_hash: str = SOURCE_HASH) -> BenefitProvenance:
    source = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url=SOURCE_URL,
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_sha256=source_hash,
        locator=f"appendix=5.3;row={row}",
        university_id=UNIVERSITY_ID,
        run_id=RUN_ID,
    )
    return BenefitProvenance(
        source=source,
        source_snapshot_hash=source_hash,
        source_run_id=RUN_ID,
        admission_year=2026,
        document_title="Приложение 5.3",
        document_kind="appendix_5_3",
        appendix_number="5.3",
        page=1,
        table="benefits",
        row=row,
        parser_version="admission-benefits-parser.v1",
    )


def _policy_version() -> BenefitPolicyVersion:
    return BenefitPolicyVersion(
        schema_version="admission-benefits-schema.v1",
        parser_version="admission-benefits-parser.v1",
        policy_version="admission-benefits-policy.v1",
    )


def _snapshot(*, source_hash: str = SOURCE_HASH) -> AdmissionBenefitsSnapshot:
    olympiad = Olympiad(
        id="olympiad:step-in-future",
        official_name="Шаг в будущее",
        organizer="МГТУ им. Н.Э. Баумана",
        rsosh_level=2,
        admission_year=2026,
        provenance=(_provenance(source_hash=source_hash),),
    )
    profile = OlympiadProfile(
        id="olympiad-profile:step-physics",
        olympiad_id=olympiad.id,
        profile_name="Физика",
        corresponding_subjects=(
            OlympiadProfileSubject(subject="физика", source_text="Физика"),
        ),
        admission_year=2026,
        provenance=(_provenance(source_hash=source_hash),),
    )
    bvi = AdmissionBenefitRule(
        id="admission-benefit:step-bvi",
        university_id=UNIVERSITY_ID,
        admission_year=2026,
        education_level=EducationLevel.BACHELOR,
        route=AdmissionRoute.OLYMPIAD,
        benefit_type=BenefitType.BVI,
        olympiad_id=olympiad.id,
        olympiad_profile_id=profile.id,
        result_type=OlympiadResultType.WINNER,
        scope=BenefitScope(
            mode=BenefitScopeMode.ALL_EXCEPT,
            targets=(
                BenefitTarget(
                    kind=BenefitTargetKind.DIRECTION,
                    value="01.03.02",
                    original_text="кроме 01.03.02",
                ),
            ),
            original_text="все направления, кроме 01.03.02",
        ),
        confirmation_requirement=ConfirmationRequirement.REQUIRED,
        confirmation_subjects=(
            ConfirmationSubjectRule(
                subject="физика",
                minimum_score=Decimal(75),
                exam_kind=ConfirmationExamKind.EGE,
                source_text="не менее 75 баллов ЕГЭ",
            ),
            ConfirmationSubjectRule(
                subject="физика",
                minimum_score=Decimal(65),
                exam_kind=ConfirmationExamKind.EGE,
                applicant_category=ConfirmationApplicantCategory.TERRITORIAL_EXCEPTION,
                source_text="для выпускников с территорий — не менее 65 баллов ЕГЭ",
            ),
        ),
        validity=ValidityPolicy(
            max_age_years=4, source_text="результат действует четыре года"
        ),
        source_text="Победитель получает БВИ",
        provenance=_provenance(source_hash=source_hash),
        policy_version=_policy_version(),
    )
    one_hundred = bvi.model_copy(
        update={
            "id": "admission-benefit:step-100",
            "benefit_type": BenefitType.ONE_HUNDRED_POINTS,
            "result_type": OlympiadResultType.PRIZE_WINNER,
            "scope": BenefitScope(
                mode=BenefitScopeMode.ONLY,
                targets=(
                    BenefitTarget(
                        kind=BenefitTargetKind.DIRECTION,
                        value="09.03.03",
                        original_text="09.03.03",
                    ),
                ),
                original_text="только 09.03.03",
            ),
            "target_subject": "физика",
            "points": Decimal(100),
            "source_text": "Призёр получает 100 баллов по физике",
            "provenance": _provenance(row=2, source_hash=source_hash),
        }
    )
    achievement = IndividualAchievementRule(
        id="individual-achievement:honors-certificate",
        university_id=UNIVERSITY_ID,
        admission_year=2026,
        education_level=EducationLevel.BACHELOR,
        achievement_code="honors_certificate",
        category="образование",
        official_name="Аттестат с отличием",
        points=Decimal(10),
        combination_group="all",
        combination_policy=AchievementCombinationPolicy.ADDITIVE,
        source_text="Аттестат с отличием — 10 баллов",
        provenance=_provenance(row=3, source_hash=source_hash),
        policy_version=_policy_version(),
    )
    policy = IndividualAchievementPolicy(
        university_id=UNIVERSITY_ID,
        admission_year=2026,
        education_level=EducationLevel.BACHELOR,
        global_max_points=Decimal(10),
        default_combination_policy=AchievementCombinationPolicy.ADDITIVE,
        rules=(achievement,),
        source_text="Суммарно не более 10 баллов",
        provenance=_provenance(row=4, source_hash=source_hash),
        policy_version=_policy_version(),
    )
    source = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url=SOURCE_URL,
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_sha256=source_hash,
        locator="appendix=5.3",
        university_id=UNIVERSITY_ID,
        run_id=RUN_ID,
    )
    return AdmissionBenefitsSnapshot(
        admission_year=2026,
        sources=(source,),
        olympiads=(olympiad,),
        olympiad_profiles=(profile,),
        benefit_rules=(bvi, one_hundred),
        individual_achievement_policy=policy,
        coverage=AdmissionBenefitCoverage(source_hashes=(source_hash,)),
    )


def _database(tmp_path: Path):
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'benefits.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            UniversityModel(
                id=UNIVERSITY_ID,
                name="МГТУ",
                city="Москва",
                official_site="https://bmstu.ru",
                address="Москва",
            )
        )
        session.add(EducationLevelModel(id=EducationLevel.BACHELOR.value))
        session.add(
            IngestRunModel(
                id=RUN_ID,
                started_at=datetime(2026, 9, 22, tzinfo=UTC),
                status="running",
            )
        )
        session.add(
            SourceSnapshotModel(
                content_sha256=SOURCE_HASH,
                ingest_run_id=RUN_ID,
                source_kind=SourceKind.BMSTU_ADMISSION_BENEFITS.value,
                requested_url=SOURCE_URL,
                final_url=SOURCE_URL,
                status_code=200,
                content_type="application/pdf",
                captured_at=datetime(2026, 9, 22, tzinfo=UTC),
                body=b"official fixture",
            )
        )
        session.add(
            SourceSnapshotModel(
                content_sha256=MANIFEST_HASH,
                ingest_run_id=RUN_ID,
                source_kind=SourceKind.BMSTU_ADMISSION_BENEFITS.value,
                requested_url=INDEX_URL,
                final_url=INDEX_URL,
                status_code=200,
                content_type="application/json",
                captured_at=datetime(2026, 9, 22, tzinfo=UTC),
                body=b"official index fixture",
            )
        )
        session.flush()
        session.add(
            DirectionModel(
                id="direction:bmstu:09.03.03",
                university_id=UNIVERSITY_ID,
                code="09.03.03",
                name="Прикладная информатика",
                education_level="bachelor",
            )
        )
        session.flush()
        session.add(
            EducationalProgramModel(
                id=PROGRAM_ID,
                direction_id="direction:bmstu:09.03.03",
                code="09.03.03-01",
                name="Профиль",
                education_year=2026,
                study_plan_url="https://bmstu.ru/plan",
                source_url="https://bmstu.ru/program",
            )
        )
    return engine


def test_repository_syncs_and_reads_both_query_directions(tmp_path: Path) -> None:
    engine = _database(tmp_path)
    snapshot = _snapshot()
    with Session(engine) as session, session.begin():
        stats = SqlAlchemyAdmissionBenefitsRepository(session).sync_snapshot(
            snapshot, source_run_id=RUN_ID
        )
        assert stats.olympiads_inserted == 1
        assert stats.rules_inserted == 2

    with Session(engine) as session:
        repository = SqlAlchemyAdmissionBenefitsRepository(session)
        statements: list[str] = []

        def capture_statement(
            _connection, _cursor, statement, _parameters, _context, _executemany
        ) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture_statement)
        rules = repository.get_rules_for_program(PROGRAM_ID, 2026)
        event.remove(engine, "before_cursor_execute", capture_statement)
        assert {rule.benefit_type for rule in rules} == {
            BenefitType.BVI,
            BenefitType.ONE_HUNDRED_POINTS,
        }
        bvi_rule = next(rule for rule in rules if rule.benefit_type is BenefitType.BVI)
        assert [subject.minimum_score for subject in bvi_rule.confirmation_subjects] == [
            Decimal("75.00"),
            Decimal("65.00"),
        ]
        assert bvi_rule.confirmation_subjects[1].applicant_category is (
            ConfirmationApplicantCategory.TERRITORIAL_EXCEPTION
        )
        assert len(statements) <= 5
        assert repository.get_programs_for_olympiad(
            "olympiad:step-in-future", UNIVERSITY_ID, 2026
        )
        policy = repository.get_individual_achievement_policy(
            UNIVERSITY_ID, 2026, EducationLevel.BACHELOR
        )
        assert policy is not None
        assert policy.rules[0].points == Decimal("10.00")


def test_policy_reader_requires_exact_active_benefit_owner_revision(tmp_path: Path) -> None:
    engine = _database(tmp_path)
    snapshot = _snapshot()
    with Session(engine) as session, session.begin():
        repository = SqlAlchemyAdmissionBenefitsRepository(session)
        repository.sync_snapshot(snapshot, source_run_id=RUN_ID)
        reader = AdmissionBenefitsPolicyRuleReader(repository)

        benefit = snapshot.benefit_rules[0]
        exact_benefit = DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            canonical_rule_id=benefit.id,
            owner_revision=1,
            owner_revision_hash=admission_benefit_revision_hash(benefit),
        )
        assert reader.lookup_rule(exact_benefit).status is PolicyDomainLookupStatus.AVAILABLE
        assert reader.lookup_rule(
            exact_benefit.model_copy(update={"owner_revision_hash": "f" * 64})
        ).status is PolicyDomainLookupStatus.NOT_FOUND
        assert reader.lookup_rule(
            exact_benefit.model_copy(update={"owner_revision_hash": None})
        ).status is PolicyDomainLookupStatus.NOT_FOUND

        achievement = snapshot.individual_achievement_policy
        assert achievement is not None
        achievement_id = individual_achievement_domain_rule_id(achievement)
        exact_achievement = DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            canonical_rule_id=achievement_id,
            owner_revision=1,
            owner_revision_hash=admission_benefit_revision_hash(achievement),
        )
        assert reader.lookup_rule(exact_achievement).status is PolicyDomainLookupStatus.AVAILABLE


def test_approved_policy_trace_delegates_exact_rules_to_existing_benefit_evaluator(
    tmp_path: Path,
) -> None:
    engine = _database(tmp_path)
    snapshot = _snapshot()
    with Session(engine) as session, session.begin():
        repository = SqlAlchemyAdmissionBenefitsRepository(session)
        repository.sync_snapshot(snapshot, source_run_id=RUN_ID)
        owner_reader = AdmissionBenefitsPolicyRuleReader(repository)
        owner_refs = [
            DomainRuleRef(
                owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
                canonical_rule_id=rule.id,
                owner_revision=1,
                owner_revision_hash=admission_benefit_revision_hash(rule),
            )
            for rule in snapshot.benefit_rules
        ]
        individual_policy = snapshot.individual_achievement_policy
        assert individual_policy is not None
        owner_refs.append(
            DomainRuleRef(
                owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
                canonical_rule_id=individual_achievement_domain_rule_id(individual_policy),
                owner_revision=1,
                owner_revision_hash=admission_benefit_revision_hash(individual_policy),
            )
        )

        captured_at = datetime(2026, 1, 1, tzinfo=UTC)
        recorded_at = datetime(2026, 1, 2, tzinfo=UTC)
        evidence = EvidenceRef(
            source_id="source:bmstu-admission",
            source_observation_id="source-observation:" + "9" * 32,
            snapshot_sha256=SOURCE_HASH,
            source_url=TypeAdapter(HttpUrl).validate_python(SOURCE_URL),
            locator=EvidenceLocator(page=1, table="benefits", row=1),
        )
        policy_revisions: list[PolicyRuleRevision] = []
        for ordinal, owner_ref in enumerate(owner_refs, start=1):
            slug = f"benefit-selection-{ordinal}"
            fields = PolicyRuleRevisionFields(
                schema_version="policy-rule.v3",
                rule_id=f"policy-rule:{slug}",
                revision=1,
                family_id=f"policy-family:{slug}",
                authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
                selector=PolicySelectorAst(
                    nodes=(
                        PolicySelectorNode(
                            node_id="root", kind=PolicySelectorNodeKind.ALL
                        ),
                        PolicySelectorNode(
                            node_id="university",
                            parent_id="root",
                            kind=PolicySelectorNodeKind.EQUALS,
                            field=PolicyContextField.UNIVERSITY_ID,
                            value=UNIVERSITY_ID,
                        ),
                        PolicySelectorNode(
                            node_id="admission-year",
                            parent_id="root",
                            kind=PolicySelectorNodeKind.EQUALS,
                            field=PolicyContextField.ADMISSION_YEAR,
                            value=2026,
                        ),
                    )
                ),
                scope=PolicyScope(
                    level=PolicyScopeLevel.UNIVERSITY,
                    scope_id=UNIVERSITY_ID,
                ),
                domain_rule=owner_ref,
                lifecycle=PolicyRevisionLifecycle.EFFECTIVE,
                temporal=PolicyTemporalRevision(
                    clock=BitemporalRevision(
                        revision=1,
                        valid_time=TemporalInterval(start=captured_at),
                        recorded_at=recorded_at,
                    ),
                    source_milestones=SourceMilestones(
                        captured_at=captured_at,
                        effective_time=TemporalInterval(start=captured_at),
                    ),
                ),
                source_claims=(
                    ClaimRevisionRef(
                        claim_id=f"claim:{ordinal:064x}", revision=1
                    ),
                ),
                evidence=(evidence,),
            )
            policy_revisions.append(
                PolicyRuleRevision(
                    **fields.model_dump(mode="python"),
                    content_hash=policy_rule_content_hash(fields),
                )
            )

        class ApprovedRules:
            def get_approved_revision(
                self, rule_id: str, revision: int, *, as_known_at=None
            ) -> PolicyRuleRevision | None:
                return next(
                    (
                        item
                        for item in policy_revisions
                        if item.rule_id == rule_id and item.revision == revision
                    ),
                    None,
                )

            def list_approved_revisions(self, *, as_known_at) -> tuple[PolicyRuleRevision, ...]:
                return tuple(policy_revisions)

            def list_approved_revision_records(
                self, *, as_known_at
            ) -> tuple[ApprovedPolicyRevision, ...]:
                records = []
                for revision in policy_revisions:
                    approved_event = create_approval_event(
                        rule_id=revision.rule_id,
                        revision=revision.revision,
                        revision_hash=revision.content_hash,
                        sequence=2,
                        kind=PolicyApprovalEventKind.APPROVED,
                        actor_account_id="account:" + "e" * 32,
                        reason="Exact policy revision reviewed.",
                        recorded_at=revision.temporal.clock.recorded_at
                        + timedelta(seconds=1),
                        preview_fingerprint="d" * 64,
                    )
                    records.append(
                        ApprovedPolicyRevision(
                            revision=revision,
                            approval_event=approved_event,
                        )
                    )
                return tuple(records)

        class CycleReader:
            def resolve_for_admission(
                self, university_id: str, admission_year: int, *, as_known_at=None
            ) -> AdmissionCycleResolution:
                if university_id != UNIVERSITY_ID or admission_year != 2026:
                    return AdmissionCycleResolution(
                        status=AdmissionCycleResolutionStatus.BLOCKED_BY_MISSING_DATA,
                        reason="No matching source-backed cycle is available.",
                    )
                return AdmissionCycleResolution(
                    status=AdmissionCycleResolutionStatus.RESOLVED,
                    cycle=AdmissionCycle(
                        cycle_id="admission-cycle:bmstu:2026",
                        revision=1,
                        university_id=UNIVERSITY_ID,
                        admission_year=2026,
                        academic_year="2026/2027",
                        application_period=InclusiveDateWindow(
                            start_date=date(2026, 6, 1), end_date=date(2026, 6, 30)
                        ),
                        enrollment_period=InclusiveDateWindow(
                            start_date=date(2026, 9, 1), end_date=date(2026, 9, 10)
                        ),
                        state=AdmissionCycleState.PUBLISHED,
                        evidence=(evidence,),
                        approved_by_account_id="account:" + "f" * 32,
                        approved_at=recorded_at,
                        approval_reason="Checked against the official admission schedule.",
                        recorded_at=recorded_at,
                    ),
                )

        class FixedClock(PolicyClock):
            def now(self) -> datetime:
                return as_known_time

        as_known_time = datetime(2026, 9, 25, tzinfo=UTC)

        resolver = EffectivePolicyResolver(
            policies=cast(ApprovedPolicyRuleReader, ApprovedRules()),
            admission_cycles=cast(PolicyAdmissionCycleReader, CycleReader()),
            domain_readers=(owner_reader,),
            clock=FixedClock(),
        )
        trace = resolver.resolve(
            PolicyResolutionRequest(
                university_id=UNIVERSITY_ID,
                admission_year=2026,
                valid_as_of=datetime(2026, 6, 15, tzinfo=UTC),
                as_known_at=as_known_time,
            )
        )
        assert trace.status.value == "resolved"

        selected_rules = []
        selected_achievement_policy = None
        for selection in trace.effective_rules:
            reference = selection.domain_rule
            assert owner_reader.lookup_rule(reference).status is PolicyDomainLookupStatus.AVAILABLE
            if reference.canonical_rule_id.startswith("admission-benefit:"):
                selected = repository.get_rule_revision(
                    reference.canonical_rule_id,
                    reference.owner_revision_hash,
                )
                assert selected is not None
                selected_rules.append(selected)
            else:
                selected_achievement_policy = repository.get_individual_achievement_policy_revision(
                    f"individual-achievement-policy:{reference.canonical_rule_id.removeprefix('individual-achievement:')}",
                    reference.owner_revision_hash,
                )
                assert selected_achievement_policy is not None

        baseline_rules = repository.get_rules_for_program(PROGRAM_ID, 2026)
        baseline_catalog = repository.get_catalog(UNIVERSITY_ID, 2026, EducationLevel.BACHELOR)
        assert baseline_catalog is not None
        request = AdmissionBenefitEvaluationInput(
            program_id=PROGRAM_ID,
            direction_code="09.03.03",
            admission_year=2026,
            education_level=EducationLevel.BACHELOR,
            applicant=ApplicantAdmissionFacts(),
            rules=baseline_rules,
            coverage=baseline_catalog.coverage,
            coverage_gaps=tuple(gap.message for gap in baseline_catalog.source_gaps),
        )
        decision_service = AdmissionDecisionService()
        baseline_result = decision_service.evaluate(
            request,
            individual_policy=individual_policy,
        )
        selected_result = decision_service.evaluate(
            request.model_copy(update={"rules": tuple(sorted(selected_rules, key=lambda item: item.id))}),
            individual_policy=selected_achievement_policy,
        )

        assert tuple(sorted(item.id for item in selected_rules)) == tuple(
            sorted(item.id for item in baseline_rules)
        )
        assert selected_achievement_policy is not None
        assert admission_benefit_revision_hash(selected_achievement_policy) == (
            admission_benefit_revision_hash(individual_policy)
        )
        assert selected_result == baseline_result
        assert selected_result.eligibility is not None
        assert all(
            item.evidence and item.evidence[0].provenance.source_snapshot_hash == SOURCE_HASH
            for item in selected_result.eligibility.evaluations
        )


def test_policy_impact_adapter_reports_typed_owner_diff_without_calculating_eligibility() -> None:
    before = _snapshot().benefit_rules[0]
    after = before.model_copy(
        update={
            "validity": before.validity.model_copy(update={"max_age_years": 2}),
        }
    )
    before_hash = admission_benefit_revision_hash(before)
    after_hash = admission_benefit_revision_hash(after)
    evidence = EvidenceRef(
        source_id="source:bmstu-admission",
        source_observation_id="source-observation:" + "1" * 32,
        snapshot_sha256=SOURCE_HASH,
        source_url=TypeAdapter(HttpUrl).validate_python(SOURCE_URL),
        locator=EvidenceLocator(page=1, table="benefits", row=1),
    )

    class ExactReader:
        def get_rule_revision(
            self, rule_id: str, revision_hash: SourceHash
        ) -> AdmissionBenefitRule | None:
            if rule_id == before.id and revision_hash == before_hash:
                return before
            if rule_id == after.id and revision_hash == after_hash:
                return after
            return None

        def get_individual_achievement_policy_revision(
            self, _policy_id: str, _hash: SourceHash
        ) -> IndividualAchievementPolicy | None:
            return None

    class EvidenceReader:
        def resolve_snapshot_evidence(
            self,
            *,
            source_url: HttpUrl,
            snapshot_sha256: SourceHash,
            locator: EvidenceLocator,
        ) -> EvidenceRef | None:
            if str(source_url) == SOURCE_URL and snapshot_sha256 == SOURCE_HASH:
                return evidence.model_copy(update={"locator": locator})
            return None

    reader = AdmissionBenefitsPolicyRuleReader(
        cast(AdmissionBenefitReader, ExactReader()),
        source_observations=cast(SourceObservationRepository, EvidenceReader()),
    )
    before_reference = DomainRuleRef(
        owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
        canonical_rule_id=before.id,
        owner_revision=1,
        owner_revision_hash=before_hash,
    )
    after_reference = before_reference.model_copy(
        update={"owner_revision": 2, "owner_revision_hash": after_hash}
    )

    result = reader.compare_policy_rules(
        before_reference,
        after_reference,
        context=PolicyImpactContext(
            university_id=UNIVERSITY_ID,
            admission_year=2026,
            context_fingerprint="c" * 64,
        ),
    )

    assert result.status is DomainImpactStatus.EVALUATED
    assert result.actionability is ImpactActionability.UNCERTAIN
    assert result.changes[0].path.endswith("validity.max_age_years")
    assert result.changes[0].before == "4"
    assert result.changes[0].after == "2"
    assert result.changes[0].before_evidence == (evidence,)
    assert result.changes[0].after_evidence == (evidence,)


def test_benefit_owner_revision_hash_ignores_mutable_review_status() -> None:
    rule = _snapshot().benefit_rules[0]
    stale = rule.model_copy(update={"status": RuleDataStatus.STALE})
    changed = rule.model_copy(update={"points": Decimal("17.00")})
    assert admission_benefit_revision_hash(rule) == admission_benefit_revision_hash(stale)
    assert admission_benefit_revision_hash(rule) != admission_benefit_revision_hash(changed)


def test_repository_same_snapshot_is_idempotent_and_changed_source_stales_old_rows(
    tmp_path: Path,
) -> None:
    engine = _database(tmp_path)
    snapshot = _snapshot()
    with Session(engine) as session, session.begin():
        repository = SqlAlchemyAdmissionBenefitsRepository(session)
        first = repository.sync_snapshot(snapshot, source_run_id=RUN_ID)
        second = repository.sync_snapshot(snapshot, source_run_id=RUN_ID)
        assert first.rules_inserted == 2
        assert second.unchanged_rows >= 2

    changed_hash = "c" * 64
    with Session(engine) as session, session.begin():
        session.add(
            SourceSnapshotModel(
                content_sha256=changed_hash,
                ingest_run_id=RUN_ID,
                source_kind=SourceKind.BMSTU_ADMISSION_BENEFITS.value,
                requested_url=SOURCE_URL,
                final_url=SOURCE_URL,
                status_code=200,
                content_type="application/pdf",
                captured_at=datetime(2026, 9, 22, tzinfo=UTC),
                body=b"changed official fixture",
            )
        )
        repository = SqlAlchemyAdmissionBenefitsRepository(session)
        repository.sync_snapshot(
            _snapshot(source_hash=changed_hash), source_run_id=RUN_ID
        )

    with Session(engine) as session:
        stale = session.scalar(
            select(func.count())
            .select_from(AdmissionBenefitRuleModel)
            .where(
                AdmissionBenefitRuleModel.source_snapshot_hash == SOURCE_HASH,
                AdmissionBenefitRuleModel.status == RuleDataStatus.STALE.value,
            )
        )
        assert stale == 2


def test_repository_keeps_unresolved_scope_round_trippable(tmp_path: Path) -> None:
    engine = _database(tmp_path)
    snapshot = _snapshot()
    unresolved_rule = snapshot.benefit_rules[0].model_copy(
        update={
            "id": "admission-benefit:unresolved",
            "scope": BenefitScope(
                mode=BenefitScopeMode.ONLY,
                targets=(
                    BenefitTarget(
                        kind=BenefitTargetKind.DIRECTION,
                        value="неизвестный код",
                        original_text="неизвестное направление",
                        resolution=TargetResolutionStatus.UNRESOLVED,
                    ),
                ),
                original_text="неизвестное направление",
            ),
            "status": RuleDataStatus.UNRESOLVED,
        }
    )
    updated = snapshot.model_copy(
        update={"benefit_rules": (*snapshot.benefit_rules, unresolved_rule)}
    )
    with Session(engine) as session, session.begin():
        SqlAlchemyAdmissionBenefitsRepository(session).sync_snapshot(
            updated, source_run_id=RUN_ID
        )
    with Session(engine) as session:
        catalog = SqlAlchemyAdmissionBenefitsRepository(session).get_catalog(
            UNIVERSITY_ID, 2026
        )
        assert catalog is not None
        unresolved = next(
            rule
            for rule in catalog.benefit_rules
            if rule.id == "admission-benefit:unresolved"
        )
        assert unresolved.scope.unresolved_targets[0].value == "неизвестный код"


def test_repository_round_trips_run_coverage_manifest_sources_and_gaps(
    tmp_path: Path,
) -> None:
    engine = _database(tmp_path)
    snapshot = _snapshot()
    manifest_source = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url=INDEX_URL,
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_sha256=MANIFEST_HASH,
        locator="document-index",
        university_id=UNIVERSITY_ID,
        run_id=RUN_ID,
    )
    gap = SourceGapReference(
        code="document_fixture_missing",
        severity=GapSeverity.DEGRADABLE,
        message="required Appendix 5.3 was not captured",
        source_url=SOURCE_URL,
        can_continue=True,
    )
    coverage = AdmissionBenefitCoverage(
        status=AdmissionBenefitCoverageStatus.PARTIAL,
        documents_discovered=11,
        documents_selected=8,
        documents_captured=7,
        documents_parsed=7,
        required_documents_expected=8,
        required_documents_discovered=8,
        required_documents_captured=7,
        records_normalized=2,
        manifest_hash=MANIFEST_HASH,
        source_hashes=(SOURCE_HASH, MANIFEST_HASH),
    )
    snapshot = snapshot.model_copy(
        update={
            "sources": (*snapshot.sources, manifest_source),
            "coverage": coverage,
            "source_gaps": (gap,),
        }
    )

    with Session(engine) as session, session.begin():
        SqlAlchemyAdmissionBenefitsRepository(session).sync_snapshot(
            snapshot, source_run_id=RUN_ID
        )

    with Session(engine) as session:
        catalog = SqlAlchemyAdmissionBenefitsRepository(session).get_catalog(
            UNIVERSITY_ID, 2026
        )
        assert catalog is not None
        assert catalog.coverage == coverage
        assert catalog.source_gaps == (gap,)
        assert {source.content_sha256 for source in catalog.sources} >= {
            SOURCE_HASH,
            MANIFEST_HASH,
        }
        persisted = session.scalar(select(AdmissionBenefitIngestionCoverageModel))
        assert persisted is not None
        assert persisted.source_run_id == RUN_ID
        assert persisted.manifest_hash == MANIFEST_HASH

    with Session(engine) as session, session.begin():
        SqlAlchemyAdmissionBenefitsRepository(session).sync_snapshot(
            snapshot, source_run_id=RUN_ID
        )
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(AdmissionBenefitIngestionCoverageModel)
            )
            == 1
        )
    engine.dispose()


def test_legacy_catalog_is_partial_and_has_explicit_coverage_gap(
    tmp_path: Path,
) -> None:
    engine = _database(tmp_path)
    with Session(engine) as session, session.begin():
        SqlAlchemyAdmissionBenefitsRepository(session).sync_snapshot(
            _snapshot(), source_run_id=RUN_ID
        )
        session.query(AdmissionBenefitIngestionCoverageModel).delete()

    with Session(engine) as session:
        catalog = SqlAlchemyAdmissionBenefitsRepository(session).get_catalog(
            UNIVERSITY_ID, 2026
        )
        assert catalog is not None
        assert catalog.coverage.status is AdmissionBenefitCoverageStatus.PARTIAL
        assert (
            catalog.source_gaps[0].code == "coverage_not_recorded_for_legacy_snapshot"
        )
    engine.dispose()


def test_partial_coverage_only_catalog_returns_insufficient_data_from_service(
    tmp_path: Path,
) -> None:
    engine = _database(tmp_path)
    gap = SourceGapReference(
        code="document_unavailable",
        severity=GapSeverity.DEGRADABLE,
        message="A required admission appendix was unavailable",
        source_url=INDEX_URL,
        can_continue=True,
    )
    coverage = AdmissionBenefitCoverage(
        status=AdmissionBenefitCoverageStatus.PARTIAL,
        documents_discovered=8,
        documents_selected=8,
        documents_captured=7,
        documents_parsed=7,
        required_documents_expected=8,
        required_documents_discovered=8,
        required_documents_captured=7,
        manifest_hash=MANIFEST_HASH,
        source_hashes=(MANIFEST_HASH,),
    )
    coverage_only = AdmissionBenefitsSnapshot(
        university_id=UNIVERSITY_ID,
        admission_year=2026,
        sources=(
            SourceAttribution(
                kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
                url=INDEX_URL,
                captured_at=datetime(2026, 9, 22, tzinfo=UTC),
                content_sha256=MANIFEST_HASH,
                university_id=UNIVERSITY_ID,
                run_id=RUN_ID,
            ),
        ),
        coverage=coverage,
        source_gaps=(gap,),
    )
    with Session(engine) as session, session.begin():
        SqlAlchemyAdmissionBenefitsRepository(session).sync_snapshot(
            coverage_only, source_run_id=RUN_ID
        )

    request = AdmissionBenefitEvaluationInput(
        program_id=PROGRAM_ID,
        direction_code="09.03.03",
        admission_year=2026,
        education_level=EducationLevel.BACHELOR,
        applicant=ApplicantAdmissionFacts(),
    )
    with Session(engine) as session:
        result = AdmissionEligibilityService(
            SqlAlchemyAdmissionBenefitsRepository(session)
        ).evaluate(
            request,
            university_id=UNIVERSITY_ID,
        )
        assert result.status is EligibilityStatus.INSUFFICIENT_DATA
        assert result.source_gaps == (
            "A required admission appendix was unavailable",
            "Source-backed admission offering lookup is unavailable",
        )
    engine.dispose()


def test_partial_run_does_not_stale_rules_from_uncaptured_source(
    tmp_path: Path,
) -> None:
    engine = _database(tmp_path)
    second_run = "ingest:" + "f" * 32
    current_index_hash = "a" * 64
    with Session(engine) as session, session.begin():
        SqlAlchemyAdmissionBenefitsRepository(session).sync_snapshot(
            _snapshot(), source_run_id=RUN_ID
        )
        session.add(
            IngestRunModel(
                id=second_run,
                started_at=datetime(2026, 9, 23, tzinfo=UTC),
                status="completed",
            )
        )
        session.add(
            SourceSnapshotModel(
                content_sha256=current_index_hash,
                ingest_run_id=second_run,
                source_kind=SourceKind.BMSTU_ADMISSION_BENEFITS.value,
                requested_url=INDEX_URL,
                final_url=INDEX_URL,
                status_code=200,
                content_type="application/json",
                captured_at=datetime(2026, 9, 23, tzinfo=UTC),
                body=b"partial index fixture",
            )
        )
        partial_snapshot = AdmissionBenefitsSnapshot(
            university_id=UNIVERSITY_ID,
            admission_year=2026,
            sources=(
                SourceAttribution(
                    kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
                    url=INDEX_URL,
                    captured_at=datetime(2026, 9, 23, tzinfo=UTC),
                    content_sha256=current_index_hash,
                    university_id=UNIVERSITY_ID,
                    run_id=second_run,
                ),
            ),
            coverage=AdmissionBenefitCoverage(
                status=AdmissionBenefitCoverageStatus.PARTIAL,
                documents_discovered=8,
                documents_selected=8,
                documents_captured=6,
                documents_parsed=6,
                required_documents_expected=8,
                required_documents_discovered=8,
                required_documents_captured=6,
                manifest_hash=current_index_hash,
                source_hashes=(current_index_hash,),
            ),
            source_gaps=(
                SourceGapReference(
                    code="required_document_not_captured",
                    severity=GapSeverity.DEGRADABLE,
                    message="One required admission document was not captured",
                    source_url=INDEX_URL,
                ),
            ),
        )
        SqlAlchemyAdmissionBenefitsRepository(session).sync_snapshot(
            partial_snapshot, source_run_id=second_run
        )

    with Session(engine) as session:
        active_count = session.scalar(
            select(func.count())
            .select_from(AdmissionBenefitRuleModel)
            .where(
                AdmissionBenefitRuleModel.source_snapshot_hash == SOURCE_HASH,
                AdmissionBenefitRuleModel.status == RuleDataStatus.ACTIVE.value,
            )
        )
        assert active_count == 2
        catalog = SqlAlchemyAdmissionBenefitsRepository(session).get_catalog(
            UNIVERSITY_ID, 2026
        )
        assert catalog is not None
        assert catalog.coverage.status is AdmissionBenefitCoverageStatus.PARTIAL
    engine.dispose()
