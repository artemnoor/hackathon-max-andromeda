from decimal import Decimal

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
    ApplicantExamScore,
)
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionRoute,
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

from .test_helpers import DIRECTION_CODE, PROGRAM_ID, olympiad_fact, olympiad_rule


def test_failed_confirmation_does_not_replace_subject_with_100() -> None:
    rule = olympiad_rule(
        benefit_type=BenefitType.ONE_HUNDRED_POINTS,
        result_type="prize_winner",
        rule_id="admission-benefit:bmstu-100-failed",
        confirmation_requirement=ConfirmationRequirement.REQUIRED,
        confirmation_subjects=(ConfirmationSubjectRule(subject="физика", minimum_score=Decimal(75), exam_kind=ConfirmationExamKind.EGE, source_text="75"),),
        target_subject="физика",
        points=Decimal(100),
    )
    request = AdmissionBenefitEvaluationInput(
        program_id=PROGRAM_ID,
        direction_code=DIRECTION_CODE,
        admission_year=2026,
        applicant=ApplicantAdmissionFacts(
            ege_scores=(ApplicantExamScore(subject="физика", score=Decimal(74)),),
            olympiad_achievements=(olympiad_fact(result_type="prize_winner"),),
        ),
        rules=(rule,),
    )
    result = AdmissionBenefitEvaluator().evaluate(request)
    assert result.status is EligibilityStatus.NOT_ELIGIBLE
    # An offering is required to calculate a competitive score; legal
    # eligibility evaluation alone must not infer one from arbitrary inputs.
    assert result.base_competitive_score is None
    assert result.effective_competitive_score is None


def test_bvi_route_does_not_turn_into_historical_passing_score() -> None:
    rule = olympiad_rule()
    request = AdmissionBenefitEvaluationInput(
        program_id=PROGRAM_ID,
        direction_code=DIRECTION_CODE,
        admission_year=2026,
        applicant=ApplicantAdmissionFacts(olympiad_achievements=(olympiad_fact(),)),
        rules=(rule,),
    )
    result = AdmissionBenefitEvaluator().evaluate(request)
    assert result.route.value == "olympiad"
    assert result.base_competitive_score is None
    assert result.effective_competitive_score is None


def test_vosh_route_is_preserved_in_eligibility_result() -> None:
    rule = olympiad_rule().model_copy(update={"route": AdmissionRoute.VOSH})
    request = AdmissionBenefitEvaluationInput(
        program_id=PROGRAM_ID,
        direction_code=DIRECTION_CODE,
        admission_year=2026,
        applicant=ApplicantAdmissionFacts(olympiad_achievements=(olympiad_fact(),)),
        rules=(rule,),
    )
    result = AdmissionBenefitEvaluator().evaluate(request)
    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.route is AdmissionRoute.VOSH
    assert result.evaluations[0].route is AdmissionRoute.VOSH
