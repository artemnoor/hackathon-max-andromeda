"""Composition of legal admission rights and individual-achievement points."""

from __future__ import annotations

import logging

from andromeda.modules.admission_benefits.contracts.public import (
    BenefitType,
    IndividualAchievementPolicy,
)
from andromeda.modules.admission_benefits.contracts.results import (
    AdmissionDecisionResult,
    AdmissionEligibilityResult,
    EligibilityStatus,
    IndividualAchievementBreakdown,
)
from andromeda.modules.admission_benefits.services.competitive_score import (
    EffectiveCompetitiveScoreCalculator,
)
from andromeda.modules.admission_benefits.services.evaluator import (
    AdmissionBenefitEvaluationInput,
    AdmissionBenefitEvaluator,
)
from andromeda.modules.admission_benefits.services.individual_achievements import (
    IndividualAchievementCalculator,
)
from andromeda.modules.admissions.contracts.public import AdmissionOffering

logger = logging.getLogger("andromeda.modules.admission_benefits.admission_decision")


class AdmissionDecisionService:
    """Return a legal route first and optional numeric readiness second."""

    def __init__(
        self,
        evaluator: AdmissionBenefitEvaluator | None = None,
        achievement_calculator: IndividualAchievementCalculator | None = None,
        competitive_score_calculator: EffectiveCompetitiveScoreCalculator | None = None,
    ) -> None:
        self._evaluator = evaluator or AdmissionBenefitEvaluator()
        self._achievement_calculator = achievement_calculator or IndividualAchievementCalculator()
        self._competitive_score_calculator = competitive_score_calculator or EffectiveCompetitiveScoreCalculator()

    def evaluate(
        self,
        request: AdmissionBenefitEvaluationInput,
        *,
        individual_policy: IndividualAchievementPolicy | None = None,
        offering: AdmissionOffering | None = None,
    ) -> AdmissionDecisionResult:
        eligibility = self._evaluator.evaluate(request)
        achievement_breakdown = None
        source_gaps = list(eligibility.source_gaps)
        if individual_policy is not None:
            if individual_policy.admission_year != request.admission_year:
                source_gaps.append("individual achievement policy year does not match request")
            else:
                excluded_codes = frozenset(
                    evaluation.matched_applicant_fact
                    for evaluation in eligibility.evaluations
                    if evaluation.status is EligibilityStatus.ELIGIBLE
                    and evaluation.benefit_type in {
                        BenefitType.BVI,
                        BenefitType.ONE_HUNDRED_POINTS,
                        BenefitType.SPECIAL_RIGHT,
                    }
                    and evaluation.matched_applicant_fact is not None
                )
                achievement_breakdown = self._achievement_calculator.calculate(
                    individual_policy,
                    request.applicant,
                    education_level=request.education_level,
                    excluded_achievement_codes=excluded_codes,
                )
                source_gaps.extend(achievement_breakdown.source_gaps)

        eligibility = _with_achievement_points(eligibility, achievement_breakdown)
        competitive_score = self._competitive_score_calculator.calculate(
            program_id=request.program_id,
            admission_year=request.admission_year,
            offering=offering,
            applicant=request.applicant,
            evaluations=eligibility.evaluations,
            rules=request.rules,
            achievement_breakdown=achievement_breakdown,
            legal_route=eligibility.route,
        )
        eligibility = eligibility.model_copy(
            update={
                "base_competitive_score": competitive_score.base_exam_score,
                "effective_competitive_score": competitive_score.post_benefit_exam_score,
            }
        )
        route = eligibility.route
        status = _decision_status(eligibility, achievement_breakdown)
        effective_score = competitive_score.effective_total
        logger.info(
            "admission_decision_complete program_id=%s year=%d route=%s status=%s id_points=%s",
            request.program_id,
            request.admission_year,
            route,
            status,
            achievement_breakdown.total_points if achievement_breakdown is not None else None,
        )
        return AdmissionDecisionResult(
            program_id=request.program_id,
            admission_year=request.admission_year,
            status=status,
            route=route,
            eligibility=eligibility,
            individual_achievements=achievement_breakdown,
            base_competitive_score=competitive_score.base_exam_score,
            individual_achievement_points=(
                achievement_breakdown.total_points if achievement_breakdown is not None else None
            ),
            effective_competitive_score=effective_score,
            competitive_score=competitive_score,
            source_gaps=tuple(dict.fromkeys(source_gaps)),
        )


def _with_achievement_points(
    eligibility: AdmissionEligibilityResult,
    breakdown: IndividualAchievementBreakdown | None,
) -> AdmissionEligibilityResult:
    if breakdown is None:
        return eligibility
    return eligibility.model_copy(update={"individual_achievement_points": breakdown.total_points})


def _decision_status(
    eligibility: AdmissionEligibilityResult,
    breakdown: IndividualAchievementBreakdown | None,
) -> EligibilityStatus:
    if eligibility.status is EligibilityStatus.REVIEW_REQUIRED:
        return EligibilityStatus.REVIEW_REQUIRED
    if breakdown is not None and breakdown.status is EligibilityStatus.REVIEW_REQUIRED:
        return EligibilityStatus.REVIEW_REQUIRED
    return eligibility.status


__all__ = ["AdmissionDecisionService"]
