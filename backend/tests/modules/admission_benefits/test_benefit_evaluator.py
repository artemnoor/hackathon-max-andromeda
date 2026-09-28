from decimal import Decimal

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
    ApplicantExamScore,
)
from andromeda.modules.admission_benefits.contracts.coverage import (
    AdmissionBenefitCoverage,
    AdmissionBenefitCoverageStatus,
)
from andromeda.modules.admission_benefits.contracts.public import (
    BenefitType,
    ConfirmationExamKind,
    ConfirmationRequirement,
    ConfirmationSubjectRule,
)
from andromeda.modules.admission_benefits.contracts.results import EligibilityStatus
from andromeda.modules.admission_benefits.services.evaluator import (
    AdmissionBenefitEvaluationInput,
    AdmissionBenefitEvaluator,
)

from .test_helpers import (
    DIRECTION_CODE,
    PROGRAM_ID,
    olympiad_fact,
    olympiad_rule,
    scope_all_except,
)


def _request(*rules, fact=None, scores=()):
    return AdmissionBenefitEvaluationInput(
        program_id=PROGRAM_ID,
        direction_code=DIRECTION_CODE,
        admission_year=2026,
        applicant=ApplicantAdmissionFacts(
            ege_scores=tuple(scores),
            olympiad_achievements=(fact,) if fact is not None else (),
        ),
        rules=tuple(rules),
    )


def test_matching_winner_gets_bvi_without_a_numeric_score() -> None:
    result = AdmissionBenefitEvaluator().evaluate(
        _request(olympiad_rule(), fact=olympiad_fact())
    )
    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.route.value == "olympiad"
    assert result.effective_competitive_score is None
    assert result.evaluations[0].benefit_type is BenefitType.BVI


def test_historical_bvi_is_not_an_evaluator_input() -> None:
    result = AdmissionBenefitEvaluator().evaluate(_request())
    assert result.status is EligibilityStatus.INSUFFICIENT_DATA
    assert result.route is None


def test_all_except_rule_rejects_an_excluded_program() -> None:
    rule = olympiad_rule(scope=scope_all_except(DIRECTION_CODE))
    result = AdmissionBenefitEvaluator().evaluate(_request(rule, fact=olympiad_fact()))
    assert result.status is EligibilityStatus.NOT_ELIGIBLE
    assert result.evaluations[0].status is EligibilityStatus.NOT_ELIGIBLE


def test_partial_source_coverage_prevents_false_negative_eligibility() -> None:
    request = _request(olympiad_rule()).model_copy(
        update={
            "coverage": AdmissionBenefitCoverage(
                status=AdmissionBenefitCoverageStatus.PARTIAL,
                documents_discovered=8,
                documents_selected=8,
                documents_captured=7,
                documents_parsed=7,
                required_documents_expected=8,
                required_documents_discovered=8,
                required_documents_captured=7,
            ),
            "coverage_gaps": ("Appendix 5.3 was not captured",),
        }
    )

    result = AdmissionBenefitEvaluator().evaluate(request)

    assert result.status is EligibilityStatus.INSUFFICIENT_DATA
    assert result.evaluations[0].status is EligibilityStatus.NOT_ELIGIBLE
    assert result.source_gaps == ("Appendix 5.3 was not captured",)


def test_inactive_rule_is_review_not_a_legal_grant() -> None:
    rule = olympiad_rule(status="review_required")
    result = AdmissionBenefitEvaluator().evaluate(_request(rule, fact=olympiad_fact()))
    assert result.status is EligibilityStatus.REVIEW_REQUIRED
    assert result.route is None


def test_rule_year_mismatch_is_fail_closed() -> None:
    rule = olympiad_rule()
    rule = rule.model_copy(update={"admission_year": 2027})
    result = AdmissionBenefitEvaluator().evaluate(_request(rule, fact=olympiad_fact()))
    assert result.status is EligibilityStatus.REVIEW_REQUIRED


def test_100_points_replaces_only_the_corresponding_ege_subject_after_confirmation() -> (
    None
):
    rule = olympiad_rule(
        benefit_type=BenefitType.ONE_HUNDRED_POINTS,
        result_type="prize_winner",
        rule_id="admission-benefit:bmstu-shag-prize-100",
        confirmation_requirement=ConfirmationRequirement.REQUIRED,
        confirmation_subjects=(
            ConfirmationSubjectRule(
                subject="информатика",
                minimum_score=Decimal(75),
                exam_kind=ConfirmationExamKind.EGE,
                source_text="Олимпиада подтверждается 75 баллами по ЕГЭ",
            ),
        ),
        target_subject="информатика",
        points=Decimal(100),
    )
    passed = AdmissionBenefitEvaluator().evaluate(
        _request(
            rule,
            fact=olympiad_fact(result_type="prize_winner"),
            scores=(
                ApplicantExamScore(subject="информатика", score=Decimal(80)),
                ApplicantExamScore(subject="русский язык", score=Decimal(90)),
            ),
        )
    )
    failed = AdmissionBenefitEvaluator().evaluate(
        _request(
            rule,
            fact=olympiad_fact(result_type="prize_winner"),
            scores=(ApplicantExamScore(subject="информатика", score=Decimal(74)),),
        )
    )
    assert passed.status is EligibilityStatus.ELIGIBLE
    assert passed.effective_competitive_score is None
    assert passed.evaluations[0].effective_score_change == Decimal(20)
    assert failed.status is EligibilityStatus.NOT_ELIGIBLE
    assert failed.effective_competitive_score is None
