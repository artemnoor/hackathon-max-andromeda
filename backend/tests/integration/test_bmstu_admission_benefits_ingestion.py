from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import (
    AdmissionBenefitRuleModel,
    IndividualAchievementRuleModel,
    RawSourceRecordModel,
)
from andromeda.infrastructure.repositories.admission_benefits import (
    SqlAlchemyAdmissionBenefitsRepository,
)
from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.contracts.source import CapturedSources, source_fetch_gap
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.ingestion.universities.bmstu.admission_benefits.release_gate import (
    evaluate_bmstu_admission_benefits_release,
)
from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
    ApplicantExamScore,
    ApplicantIndividualAchievement,
    ApplicantOlympiadAchievement,
)
from andromeda.modules.admission_benefits.contracts.coverage import (
    AdmissionBenefitCoverageStatus,
)
from andromeda.modules.admission_benefits.contracts.public import (
    AchievementCombinationPolicy,
    AdmissionRoute,
    BenefitType,
    ConfirmationApplicantCategory,
    ConfirmationExamKind,
    ConfirmationRequirement,
)
from andromeda.modules.admission_benefits.contracts.results import (
    IndividualAchievementStatus,
)
from andromeda.modules.admission_benefits.services.evaluator import (
    AdmissionBenefitEvaluationInput,
    AdmissionBenefitEvaluator,
)
from andromeda.modules.admission_benefits.services.individual_achievements import (
    IndividualAchievementCalculator,
)
from andromeda.modules.admissions.contracts.subject_identity import canonical_subject_key
from andromeda.modules.entity_resolution.contracts.public import (
    ResolutionContext,
    ResolutionEntityType,
    ResolutionStatus,
)
from andromeda.modules.entity_resolution.services.resolvers import (
    CachedEntityCatalog,
    EntityResolverService,
)

TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
BENEFIT_FIXTURE_DIR = (
    Path(__file__).parents[1]
    / "ingestion"
    / "fixtures"
    / "bmstu"
    / "admission_benefits"
)
RUN_ID = "ingest:" + "b" * 32


class _EmptyEntityCatalog:
    def list_universities(self):
        return ()

    def list_directions(self):
        return ()

    def list_programs(self):
        return ()

    def list_disciplines(self):
        return ()


class _SourceBoundCandidateSelector:
    def __init__(self, selected_id: str) -> None:
        self.selected_id = selected_id
        self.candidates = ()
        self.calls = 0

    def select(self, query, candidates):
        self.calls += 1
        self.candidates = candidates
        return self.selected_id


def _benefit_snapshot(file_name: str, document_kind: str) -> RawSourceSnapshot:
    payload = json.loads((BENEFIT_FIXTURE_DIR / file_name).read_text(encoding="utf-8"))
    url = payload["source_url"]
    return RawSourceSnapshot(
        source_kind=f"bmstu_admission_document:{document_kind}",
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="application/json",
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_sha256=payload["content_sha256"],
        body=(BENEFIT_FIXTURE_DIR / file_name).read_bytes(),
        access_mode="fixture",
    )


def _olympiad_profile_snapshot(file_name: str, profile_key: str) -> RawSourceSnapshot:
    payload = json.loads((BENEFIT_FIXTURE_DIR / file_name).read_text(encoding="utf-8"))
    url = payload["source_url"]
    return RawSourceSnapshot(
        source_kind=f"bmstu_olympiad_profile:{profile_key}",
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="application/json",
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_sha256=payload["content_sha256"],
        body=(BENEFIT_FIXTURE_DIR / file_name).read_bytes(),
        access_mode="fixture",
    )


def test_official_bmstu_extracts_are_persisted_in_the_existing_ingestion_transaction(
    tmp_path: Path,
) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        captured = adapter.capture(mode="fixture", fixture_dir=TRACER_FIXTURE_DIR)
        captured = CapturedSources(
            snapshots=(
                *captured.snapshots,
                _benefit_snapshot("appendix-5-1-extract.json", "appendix_5_1"),
                _benefit_snapshot("appendix-5-2-extract.json", "appendix_5_2"),
                _benefit_snapshot("appendix-5-3-extract.json", "appendix_5_3"),
                _benefit_snapshot("appendix-5-4-extract.json", "appendix_5_4"),
                _benefit_snapshot("appendix-5-5-extract.json", "appendix_5_5"),
                _benefit_snapshot("appendix-6-extract.json", "appendix_6"),
                _benefit_snapshot("rules-2026.extract.json", "rules"),
                _olympiad_profile_snapshot(
                    "shag-engineering.html.extract.json", "engineering"
                ),
                _olympiad_profile_snapshot(
                    "shag-programming.html.extract.json", "programming"
                ),
            ),
            source_gaps=(
                *captured.source_gaps,
                source_fetch_gap(
                    "bmstu_admission_document:appendix_5",
                    "https://api.www.bmstu.ru/file/122219/download",
                    "document_unavailable",
                ),
            ),
        )
        raw, canonical = adapter.parse(
            captured, source_run_id=RUN_ID, admission_year=2026
        )
    finally:
        adapter.close()

    assert raw.admission_benefit_records
    assert canonical.admission_benefits is not None
    assert canonical.admission_benefits.admission_year == 2026
    assert canonical.admission_benefits.benefit_rules
    assert canonical.admission_benefits.individual_achievement_policy is not None

    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'benefits.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.start_run(run_id=RUN_ID, university_id=canonical.university.id)
    repository.ingest(raw, canonical, run_id=RUN_ID)

    with Session(engine) as session:
        assert session.scalar(select(AdmissionBenefitRuleModel.id)) is not None
        assert session.scalar(select(IndividualAchievementRuleModel.id)) is not None
        benefit_raw_count = session.scalar(
            select(RawSourceRecordModel.id)
            .where(RawSourceRecordModel.record_type == "AdmissionBenefit")
            .limit(1)
        )
        assert benefit_raw_count is not None
        catalog = SqlAlchemyAdmissionBenefitsRepository(session).get_catalog(
            "university:bmstu", 2026
        )
        assert catalog is not None
        assert catalog.coverage.status is AdmissionBenefitCoverageStatus.PARTIAL
        assert any(gap.code == "document_unavailable" for gap in catalog.source_gaps)
        release_report = evaluate_bmstu_admission_benefits_release(catalog)
        assert not release_report.production_ready
        assert not release_report.coverage_complete
        assert release_report.source_gaps > 0
        assert release_report.achievement_rules_active > 0
        assert release_report.achievement_policy_status.value == "active"

        engineering_profile = next(
            profile
            for profile in catalog.olympiad_profiles
            if profile.profile_name.casefold()
            == "\u0438\u043d\u0436\u0435\u043d\u0435\u0440\u043d\u043e\u0435 \u0434\u0435\u043b\u043e"
        )
        benefit_reader = SqlAlchemyAdmissionBenefitsRepository(session)
        selector = _SourceBoundCandidateSelector(engineering_profile.id)
        resolver = EntityResolverService(
            CachedEntityCatalog(_EmptyEntityCatalog()),
            admission_benefit_reader=benefit_reader,
            candidate_selector=selector,
        )
        resolved_profile = resolver.resolve(
            ResolutionEntityType.OLYMPIAD_PROFILE,
            "\u044f \u043f\u0440\u0438\u0437\u0451\u0440 \u043e\u043b\u0438\u043c\u043f\u0438\u0430\u0434\u044b \u0448\u0430\u0433 \u0432 \u0431\u0443\u0434\u0443\u0449\u0435\u0435 \u043f\u043e \u043f\u0440\u043e\u0444\u0438\u043b\u044e "
            + engineering_profile.profile_name,
            context=ResolutionContext(
                university_id="university:bmstu", admission_year=2026
            ),
        )
        assert resolved_profile.status is ResolutionStatus.RESOLVED
        assert resolved_profile.selected_id == engineering_profile.id
        assert selector.calls == 0

        eligible_rule_and_campus = next(
            (
                (rule, campus_id)
                for campus_id in (
                    None,
                    "campus:bmstu-kaluga",
                    "campus:bmstu-mytishchi",
                )
                for rule in benefit_reader.get_rules_for_program(
                    "program:bmstu:09.03.01-02",
                    2026,
                    include_review=True,
                    campus_id=campus_id,
                )
                if rule.olympiad_profile_id == resolved_profile.selected_id
                and rule.route is AdmissionRoute.OLYMPIAD
                and rule.benefit_type is BenefitType.BVI
                and rule.status.value == "active"
                and rule.result_type is not None
                and rule.confirmation_requirement is not ConfirmationRequirement.UNKNOWN
                and rule.scope.applies_to(
                    direction_code="09.03.01",
                    program_id="program:bmstu:09.03.01-02",
                    campus_id=campus_id,
                ).status.value
                == "applicable"
            ),
            None,
        )
        assert eligible_rule_and_campus is not None
        resolved_bvi_rule, resolved_campus = eligible_rule_and_campus
        confirmation_subject = None
        confirmation_scores = ()
        if (
            resolved_bvi_rule.confirmation_requirement
            is ConfirmationRequirement.REQUIRED
        ):
            profile_subject_keys = {
                canonical_subject_key(item.subject)
                for item in engineering_profile.corresponding_subjects
            }
            confirmation_rule = next(
                subject
                for subject in resolved_bvi_rule.confirmation_subjects
                if canonical_subject_key(subject.subject) in profile_subject_keys
                and subject.minimum_score is not None
                and subject.exam_kind is ConfirmationExamKind.EGE
                and subject.applicant_category
                is not ConfirmationApplicantCategory.TERRITORIAL_EXCEPTION
            )
            confirmation_subject = confirmation_rule.subject
            confirmation_scores = (
                ApplicantExamScore(
                    subject=confirmation_rule.subject,
                    score=confirmation_rule.minimum_score,
                ),
            )
        resolved_applicant = ApplicantAdmissionFacts(
            ege_scores=confirmation_scores,
            olympiad_achievements=(
                ApplicantOlympiadAchievement(
                    olympiad_id=resolved_bvi_rule.olympiad_id,
                    olympiad_profile_id=resolved_profile.selected_id,
                    result_year=2026,
                    result_type=resolved_bvi_rule.result_type,
                    confirmation_subject=confirmation_subject,
                ),
            ),
            confirmation_category=ConfirmationApplicantCategory.STANDARD,
        )
        resolved_eligibility = AdmissionBenefitEvaluator().evaluate(
            AdmissionBenefitEvaluationInput(
                program_id="program:bmstu:09.03.01-02",
                direction_code="09.03.01",
                admission_year=2026,
                campus_id=resolved_campus,
                applicant=resolved_applicant,
                rules=(resolved_bvi_rule,),
            )
        )
        assert resolved_eligibility.status.value == "eligible"
        assert resolved_eligibility.route is AdmissionRoute.OLYMPIAD

        hundred_rule_and_campus = next(
            (
                (rule, campus_id)
                for campus_id in (
                    None,
                    "campus:bmstu-kaluga",
                    "campus:bmstu-mytishchi",
                )
                for rule in catalog.benefit_rules
                if rule.benefit_type is BenefitType.ONE_HUNDRED_POINTS
                and rule.status.value == "active"
                and rule.olympiad_id is not None
                and rule.result_type is not None
                and rule.confirmation_requirement is ConfirmationRequirement.REQUIRED
                and rule.target_subject is not None
                and rule.scope.applies_to(
                    direction_code="09.03.01",
                    program_id="program:bmstu:09.03.01-02",
                    campus_id=campus_id,
                ).status.value
                == "applicable"
            ),
            None,
        )
        assert hundred_rule_and_campus is not None
        hundred_rule, hundred_campus = hundred_rule_and_campus
        threshold_subject = next(
            subject
            for subject in hundred_rule.confirmation_subjects
            if subject.minimum_score == Decimal(75)
            and subject.exam_kind is ConfirmationExamKind.EGE
            and subject.applicant_category
            is not ConfirmationApplicantCategory.TERRITORIAL_EXCEPTION
        )

        def evaluate_hundred_point_right(score: int):
            applicant = ApplicantAdmissionFacts(
                ege_scores=(
                    ApplicantExamScore(
                        subject=threshold_subject.subject,
                        score=Decimal(score),
                    ),
                ),
                olympiad_achievements=(
                    ApplicantOlympiadAchievement(
                        olympiad_id=hundred_rule.olympiad_id,
                        olympiad_profile_id=hundred_rule.olympiad_profile_id,
                        result_year=2026,
                        result_type=hundred_rule.result_type,
                        confirmation_subject=threshold_subject.subject,
                    ),
                ),
                confirmation_category=ConfirmationApplicantCategory.STANDARD,
            )
            return AdmissionBenefitEvaluator().evaluate(
                AdmissionBenefitEvaluationInput(
                    program_id="program:bmstu:09.03.01-02",
                    direction_code="09.03.01",
                    admission_year=2026,
                    campus_id=hundred_campus,
                    applicant=applicant,
                    rules=(hundred_rule,),
                )
            )

        failed_confirmation = evaluate_hundred_point_right(74)
        passed_confirmation = evaluate_hundred_point_right(75)
        assert (
            failed_confirmation.evaluations[0].status.value != "eligible"
        ), (
            failed_confirmation.evaluations[0].rejection_reason,
            failed_confirmation.source_gaps,
        )
        assert (
            passed_confirmation.evaluations[0].status.value == "eligible"
        ), (
            passed_confirmation.evaluations[0].rejection_reason,
            passed_confirmation.source_gaps,
        )

        active_hundred_rule = next(
            rule
            for rule in catalog.benefit_rules
            if rule.benefit_type.value == "one_hundred_points"
            and rule.status.value == "active"
        )
        unsafe_catalog = catalog.model_copy(
            update={
                "benefit_rules": tuple(
                    rule.model_copy(update={"target_subject": None})
                    if rule.id == active_hundred_rule.id
                    else rule
                    for rule in catalog.benefit_rules
                )
            }
        )
        unsafe_report = evaluate_bmstu_admission_benefits_release(unsafe_catalog)
        assert unsafe_report.active_100_point_rules_without_subject >= 1
        assert "active_100_point_rule_missing_target_subject" in unsafe_report.blockers

        branch_rule = next(
            rule
            for rule in catalog.benefit_rules
            if rule.provenance.appendix_number == "5_2"
        )
        assert {target.value for target in branch_rule.scope.targets} == {
            "campus:bmstu-kaluga",
            "campus:bmstu-mytishchi",
        }
        branch_applicant = ApplicantAdmissionFacts(
            ege_scores=(
                ApplicantExamScore(subject="обществознание", score=Decimal("80")),
            ),
            olympiad_achievements=(
                ApplicantOlympiadAchievement(
                    olympiad_id=branch_rule.olympiad_id,
                    olympiad_profile_id=branch_rule.olympiad_profile_id,
                    result_year=2026,
                    result_type=branch_rule.result_type,
                ),
            ),
        )
        branch_result = AdmissionBenefitEvaluator().evaluate(
            AdmissionBenefitEvaluationInput(
                program_id="program:bmstu:09.03.01-02",
                direction_code="09.03.01",
                admission_year=2026,
                campus_id="campus:bmstu-kaluga",
                applicant=branch_applicant,
                rules=(branch_rule,),
            )
        )
        moscow_result = AdmissionBenefitEvaluator().evaluate(
            AdmissionBenefitEvaluationInput(
                program_id="program:bmstu:09.03.01-02",
                direction_code="09.03.01",
                admission_year=2026,
                campus_id="campus:bmstu-moscow",
                applicant=branch_applicant,
                rules=(branch_rule,),
            )
        )
        assert branch_result.status.value == "eligible"
        assert moscow_result.status.value == "not_eligible"
        step_in_future = next(
            item for item in catalog.olympiads if "Шаг в будущее" in item.official_name
        )
        step_rules = [
            rule
            for rule in catalog.benefit_rules
            if rule.olympiad_id == step_in_future.id
        ]
        assert step_rules
        assert any(rule.validity.max_age_years == 4 for rule in step_rules)
        assert any(
            subject.minimum_score == 65
            and subject.applicant_category.value == "territorial_exception"
            for rule in step_rules
            for subject in rule.confirmation_subjects
        )
        conditions = [condition for rule in step_rules for condition in rule.conditions]
        confirmation_evidence = next(
            condition.provenance
            for condition in conditions
            if condition.kind.value == "confirmation_score"
            and condition.provenance is not None
        )
        validity_evidence = next(
            condition.provenance
            for condition in conditions
            if condition.kind.value == "validity" and condition.provenance is not None
        )
        assert confirmation_evidence is not None
        assert "page=12;section=1.12" in confirmation_evidence.source.locator
        assert validity_evidence is not None
        assert "page=12;section=1.11" in validity_evidence.source.locator

        achievement_policy = catalog.individual_achievement_policy
        assert achievement_policy is not None
        assert len(achievement_policy.rules) == 82
        assert {rule.provenance.row for rule in achievement_policy.rules} == set(
            range(1, 47)
        )
        assert achievement_policy.global_max_points == 10
        assert (
            achievement_policy.default_combination_policy
            is AchievementCombinationPolicy.ADDITIVE
        )
        assert achievement_policy.provenance.page == 7
        assert (
            achievement_policy.provenance.source.content_sha256
            == "5ae90e108dc8940b37fe3b07f211664b7871791792abdc6ddc0dd365fb948bb9"
        )
        honor_certificate = next(
            rule
            for rule in achievement_policy.rules
            if rule.provenance.row == 1 and rule.points == 10
        )
        gto_rules = [
            rule for rule in achievement_policy.rules if rule.provenance.row == 5
        ]
        assert {rule.points for rule in gto_rules} == {5, 4, 3}
        gto_policy_evidence = next(
            condition.provenance
            for rule in gto_rules
            for condition in rule.conditions
            if condition.normalized_value == "appendix_6_note:4"
        )
        assert gto_policy_evidence is not None
        assert gto_policy_evidence.page == 8
        assert "document_note=4" in (gto_policy_evidence.source.locator or "")
        applicant = ApplicantAdmissionFacts(
            individual_achievements=(
                ApplicantIndividualAchievement(
                    achievement_code=honor_certificate.achievement_code,
                    year=2026,
                    evidence_reference="document-present:honors-certificate",
                ),
                *(
                    ApplicantIndividualAchievement(
                        achievement_code=rule.achievement_code,
                        year=2026,
                        evidence_reference="document-present:gto-certificate",
                    )
                    for rule in gto_rules
                ),
            )
        )
        achievement_result = IndividualAchievementCalculator().calculate(
            achievement_policy,
            applicant,
        )
        assert achievement_result.global_cap == 10
        assert achievement_result.uncapped_points == 15
        assert achievement_result.total_points == 10
        gold_gto = next(
            item for item in achievement_result.evaluations if item.rule_points == 5
        )
        assert gold_gto.status is IndividualAchievementStatus.CAPPED
        assert gold_gto.awarded_points == 0
        assert (
            sum(
                item.status is IndividualAchievementStatus.DEDUPLICATED
                for item in achievement_result.evaluations
            )
            == 2
        )
        reversed_result = IndividualAchievementCalculator().calculate(
            achievement_policy,
            ApplicantAdmissionFacts(
                individual_achievements=tuple(
                    reversed(applicant.individual_achievements)
                )
            ),
        )
        assert {
            item.achievement_code: (item.status, item.awarded_points)
            for item in achievement_result.evaluations
        } == {
            item.achievement_code: (item.status, item.awarded_points)
            for item in reversed_result.evaluations
        }
    engine.dispose()
