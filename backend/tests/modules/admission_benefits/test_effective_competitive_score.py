from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
    ApplicantExamScore,
)
from andromeda.modules.admission_benefits.contracts.public import (
    BenefitType,
    ConfirmationExamKind,
    ConfirmationRequirement,
    ConfirmationSubjectRule,
)
from andromeda.modules.admission_benefits.contracts.results import (
    CompetitiveScoreStatus,
    EligibilityStatus,
)
from andromeda.modules.admission_benefits.services.admission_decision import (
    AdmissionDecisionService,
)
from andromeda.modules.admission_benefits.services.evaluator import (
    AdmissionBenefitEvaluationInput,
)
from andromeda.modules.admissions.contracts.public import (
    AdmissionOffering,
    AdmissionProvenance,
    AdmissionScope,
    ExamRequirement,
    FundingType,
    StudyForm,
)

from .test_helpers import (
    DIRECTION_CODE,
    PROGRAM_ID,
    achievement_policy,
    achievement_rule,
    olympiad_fact,
    olympiad_rule,
)


def _provenance() -> AdmissionProvenance:
    return AdmissionProvenance(
        source_kind="bmstu_major_detail",
        source_url="https://api.www.bmstu.ru/majors/example",
        captured_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        content_sha256="c" * 64,
    )


def _exam(
    subject: str,
    *,
    minimum: str | None = None,
    choice: bool = False,
    group: str | None = None,
) -> ExamRequirement:
    return ExamRequirement(
        subject=subject,
        source_name=subject,
        minimum_score=Decimal(minimum) if minimum else None,
        is_choice=choice,
        is_required=not choice,
        choice_group_id=group,
        choice_group_min=1 if group else None,
        choice_group_max=1 if group else None,
        provenance=_provenance(),
    )


def _offering(*exams: ExamRequirement) -> AdmissionOffering:
    return AdmissionOffering(
        id="admission-offering:program:bmstu:09.03.03-01:2026:full_time:budget:direction",
        program_id=PROGRAM_ID,
        admission_year=2026,
        study_form=StudyForm.FULL_TIME,
        funding_type=FundingType.BUDGET,
        scope=AdmissionScope.DIRECTION,
        exams=tuple(exams),
        provenance=(_provenance(),),
    )


def _request(
    applicant: ApplicantAdmissionFacts, *, rules=()
) -> AdmissionBenefitEvaluationInput:
    return AdmissionBenefitEvaluationInput(
        program_id=PROGRAM_ID,
        direction_code=DIRECTION_CODE,
        admission_year=2026,
        applicant=applicant,
        rules=tuple(rules),
    )


def _empty_claims_policy():
    return achievement_policy(achievement_rule("gto_gold", "5"), global_max_points="10")


def test_selects_only_one_source_defined_exam_choice_instead_of_summing_all_ege() -> (
    None
):
    group = "exam-choice:third-ege"
    applicant = ApplicantAdmissionFacts(
        ege_scores=(
            ApplicantExamScore(subject="Русский язык", score=Decimal("90")),
            ApplicantExamScore(subject="Математика профильная", score=Decimal("88")),
            ApplicantExamScore(subject="Физика", score=Decimal("80")),
            ApplicantExamScore(subject="Информатика", score=Decimal("95")),
        )
    )
    result = AdmissionDecisionService().evaluate(
        _request(applicant),
        individual_policy=_empty_claims_policy(),
        offering=_offering(
            _exam("Русский язык"),
            _exam("Математика", minimum="40"),
            _exam("Физика", choice=True, group=group),
            _exam("Информатика", choice=True, group=group),
        ),
    )

    assert result.competitive_score is not None
    assert result.competitive_score.status is CompetitiveScoreStatus.AVAILABLE
    assert result.competitive_score.selected_exam_combination == (
        "Информатика",
        "Математика",
        "Русский язык",
    )
    assert result.competitive_score.base_exam_score == Decimal("273")
    assert result.effective_competitive_score == Decimal("273")
    assert result.effective_competitive_score != Decimal("353")


def test_confirmed_hundred_point_right_replaces_missing_target_score() -> None:
    rule = olympiad_rule(
        benefit_type=BenefitType.ONE_HUNDRED_POINTS,
        result_type="prize_winner",
        rule_id="admission-benefit:physics-100",
        confirmation_requirement=ConfirmationRequirement.REQUIRED,
        confirmation_subjects=(
            ConfirmationSubjectRule(
                subject="информатика",
                minimum_score=Decimal("75"),
                exam_kind=ConfirmationExamKind.EGE,
                source_text="Информатика >= 75",
            ),
        ),
        target_subject="физика",
        points=Decimal("100"),
    )
    applicant = ApplicantAdmissionFacts(
        ege_scores=(
            ApplicantExamScore(subject="Русский язык", score=Decimal("90")),
            ApplicantExamScore(subject="Информатика", score=Decimal("80")),
        ),
        olympiad_achievements=(olympiad_fact(result_type="prize_winner"),),
    )
    result = AdmissionDecisionService().evaluate(
        _request(applicant, rules=(rule,)),
        individual_policy=_empty_claims_policy(),
        offering=_offering(_exam("Русский язык"), _exam("Физика")),
    )

    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.competitive_score is not None
    assert result.competitive_score.exam_scores_before[-1].raw_score is None
    assert result.competitive_score.exam_scores_after_benefits[
        -1
    ].effective_score == Decimal("100")
    assert result.competitive_score.exam_scores_after_benefits[
        -1
    ].applied_benefit_rule_ids == (rule.id,)
    assert result.competitive_score.base_exam_score is None
    assert result.effective_competitive_score == Decimal("190")


def test_below_offering_minimum_has_no_numeric_competitive_total() -> None:
    applicant = ApplicantAdmissionFacts(
        ege_scores=(ApplicantExamScore(subject="Русский язык", score=Decimal("35")),)
    )
    result = AdmissionDecisionService().evaluate(
        _request(applicant),
        individual_policy=_empty_claims_policy(),
        offering=_offering(_exam("Русский язык", minimum="40")),
    )

    assert result.competitive_score is not None
    assert result.competitive_score.status is CompetitiveScoreStatus.NOT_APPLICABLE
    assert result.effective_competitive_score is None


def test_unknown_choice_cardinality_fails_closed() -> None:
    offering = AdmissionOffering(
        id="admission-offering:program:bmstu:09.03.03-01:2026:full_time:budget:direction",
        program_id=PROGRAM_ID,
        admission_year=2026,
        scope=AdmissionScope.DIRECTION,
        exams=(_exam("Физика", choice=True), _exam("Информатика", choice=True)),
        provenance=(_provenance(),),
    )
    result = AdmissionDecisionService().evaluate(
        _request(
            ApplicantAdmissionFacts(
                ege_scores=(ApplicantExamScore(subject="Физика", score=Decimal("95")),)
            )
        ),
        individual_policy=_empty_claims_policy(),
        offering=offering,
    )

    assert result.competitive_score is not None
    assert result.competitive_score.status is CompetitiveScoreStatus.INSUFFICIENT_DATA
    assert result.effective_competitive_score is None


def test_bvi_route_does_not_report_general_competitive_score() -> None:
    result = AdmissionDecisionService().evaluate(
        _request(
            ApplicantAdmissionFacts(olympiad_achievements=(olympiad_fact(),)),
            rules=(olympiad_rule(),),
        ),
    )

    assert result.route is not None
    assert result.competitive_score is not None
    assert result.competitive_score.status is CompetitiveScoreStatus.NOT_APPLICABLE
    assert result.effective_competitive_score is None
