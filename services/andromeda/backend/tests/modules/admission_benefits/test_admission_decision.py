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
from andromeda.modules.admission_benefits.contracts.results import EligibilityStatus
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
)

from .test_helpers import (
    DIRECTION_CODE,
    PROGRAM_ID,
    achievement_fact,
    achievement_policy,
    achievement_rule,
    olympiad_fact,
    olympiad_rule,
)


def test_bvi_is_primary_and_is_not_presented_as_a_passing_score() -> None:
    request = AdmissionBenefitEvaluationInput(
        program_id=PROGRAM_ID,
        direction_code=DIRECTION_CODE,
        admission_year=2026,
        applicant=ApplicantAdmissionFacts(
            ege_scores=(ApplicantExamScore(subject="русский язык", score=Decimal("90")),),
            olympiad_achievements=(olympiad_fact(),),
        ),
        rules=(olympiad_rule(),),
    )
    result = AdmissionDecisionService().evaluate(request)
    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.route.value == "olympiad"
    assert result.effective_competitive_score is None


def test_100_points_and_individual_achievements_compose_after_legal_evaluation() -> None:
    rule = olympiad_rule(
        benefit_type=BenefitType.ONE_HUNDRED_POINTS,
        result_type="prize_winner",
        rule_id="admission-benefit:bmstu-prize-100-with-id",
        confirmation_requirement=ConfirmationRequirement.REQUIRED,
        confirmation_subjects=(ConfirmationSubjectRule(subject="информатика", minimum_score=Decimal("75"), exam_kind=ConfirmationExamKind.EGE, source_text="75"),),
        target_subject="информатика",
        points=Decimal("100"),
    )
    policy = achievement_policy(
        achievement_rule("gto_gold", "5"),
        achievement_rule("olympiad:shag-v-budushchee", "5"),
        global_max_points="10",
    )
    request = AdmissionBenefitEvaluationInput(
        program_id=PROGRAM_ID,
        direction_code=DIRECTION_CODE,
        admission_year=2026,
        applicant=ApplicantAdmissionFacts(
            ege_scores=(ApplicantExamScore(subject="информатика", score=Decimal("80")), ApplicantExamScore(subject="русский язык", score=Decimal("90"))),
            olympiad_achievements=(olympiad_fact(result_type="prize_winner"),),
            individual_achievements=(achievement_fact("gto_gold"), achievement_fact("olympiad:shag-v-budushchee")),
        ),
        rules=(rule,),
    )
    source = AdmissionProvenance(
        source_kind="bmstu_major_detail",
        source_url="https://api.www.bmstu.ru/majors/example",
        captured_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        content_sha256="d" * 64,
    )
    offering = AdmissionOffering(
        id="admission-offering:program:09.03.03-01:2026:full_time:budget:direction",
        program_id=PROGRAM_ID,
        admission_year=2026,
        scope=AdmissionScope.DIRECTION,
        exams=(
            ExamRequirement(subject="Информатика", source_name="Информатика", provenance=source),
            ExamRequirement(subject="Русский язык", source_name="Русский язык", provenance=source),
        ),
        provenance=(source,),
    )
    result = AdmissionDecisionService().evaluate(request, individual_policy=policy, offering=offering)
    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.individual_achievement_points == Decimal("5")
    assert result.effective_competitive_score == Decimal("195")
    assert result.individual_achievements is not None
    assert result.individual_achievements.evaluations[1].status.value == "excluded"
