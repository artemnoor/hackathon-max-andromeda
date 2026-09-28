"""Explainable deterministic benefit-evaluation results."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from andromeda.modules.admissions.contracts.public import AdmissionProvenance
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    AdmissionBenefitRuleId,
    EducationYear,
    IndividualAchievementRuleId,
    NonEmptyText,
    ProgramId,
    ShortText,
)

from .provenance import BenefitProvenance
from .public import (
    AchievementCombinationPolicy,
    AdmissionRoute,
    BenefitType,
    OlympiadResultType,
)


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    INSUFFICIENT_DATA = "insufficient_data"
    REVIEW_REQUIRED = "review_required"


class AdmissionBenefitEvidence(ContractModel):
    rule_id: AdmissionBenefitRuleId | IndividualAchievementRuleId
    provenance: BenefitProvenance
    excerpt: ShortText | None = None


class AdmissionBenefitEvaluation(ContractModel):
    rule_id: AdmissionBenefitRuleId
    benefit_type: BenefitType
    route: AdmissionRoute | None = None
    status: EligibilityStatus
    result_type: OlympiadResultType | None = None
    matched_applicant_fact: ShortText | None = None
    rejection_reason: ShortText | None = None
    effective_score_change: Decimal | None = None
    points_contribution: Decimal | None = None
    evidence: tuple[AdmissionBenefitEvidence, ...] = Field(min_length=1)


class IndividualAchievementStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REVIEW_REQUIRED = "review_required"
    DEDUPLICATED = "deduplicated"
    CAPPED = "capped"
    EXCLUDED = "excluded"


class IndividualAchievementEvaluation(ContractModel):
    rule_id: IndividualAchievementRuleId | None = None
    achievement_code: NonEmptyText
    status: IndividualAchievementStatus
    applicant_year: EducationYear | None = None
    rule_points: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(100), max_digits=5, decimal_places=2)
    awarded_points: Decimal = Field(strict=True, ge=Decimal(0), le=Decimal(100), max_digits=5, decimal_places=2)
    combination_policy: AchievementCombinationPolicy | None = None
    reason: ShortText
    evidence: tuple[AdmissionBenefitEvidence, ...] = ()


class IndividualAchievementBreakdown(ContractModel):
    status: EligibilityStatus
    total_points: Decimal = Field(strict=True, ge=Decimal(0), le=Decimal(100), max_digits=6, decimal_places=2)
    uncapped_points: Decimal = Field(strict=True, ge=Decimal(0), le=Decimal(100), max_digits=6, decimal_places=2)
    global_cap: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(100), max_digits=5, decimal_places=2)
    evaluations: tuple[IndividualAchievementEvaluation, ...] = ()
    source_gaps: tuple[ShortText, ...] = ()


class CompetitiveScoreStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_APPLICABLE = "not_applicable"


class CompetitiveExamScore(ContractModel):
    subject: NonEmptyText
    source_name: NonEmptyText
    raw_score: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(100), max_digits=5, decimal_places=2)
    effective_score: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(100), max_digits=5, decimal_places=2)
    minimum_score: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(100), max_digits=5, decimal_places=2)
    applied_benefit_rule_ids: tuple[AdmissionBenefitRuleId, ...] = ()
    provenance: tuple[AdmissionProvenance, ...] = Field(min_length=1)


class EffectiveCompetitiveScore(ContractModel):
    """Offering-specific and reproducible competitive-score calculation."""

    status: CompetitiveScoreStatus
    offering_id: NonEmptyText | None = None
    available_offering_ids: tuple[NonEmptyText, ...] = ()
    selected_exam_combination: tuple[NonEmptyText, ...] = ()
    exam_scores_before: tuple[CompetitiveExamScore, ...] = ()
    exam_scores_after_benefits: tuple[CompetitiveExamScore, ...] = ()
    candidate_exams_considered: int = Field(default=0, strict=True, ge=0)
    base_exam_score: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(500), max_digits=6, decimal_places=2)
    post_benefit_exam_score: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(500), max_digits=6, decimal_places=2)
    individual_achievement_points: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(100), max_digits=6, decimal_places=2)
    effective_total: Decimal | None = Field(default=None, strict=True, ge=Decimal(0), le=Decimal(600), max_digits=6, decimal_places=2)
    source_gaps: tuple[ShortText, ...] = ()


class AdmissionEligibilityResult(ContractModel):
    program_id: ProgramId
    admission_year: EducationYear
    status: EligibilityStatus
    route: AdmissionRoute | None = None
    evaluations: tuple[AdmissionBenefitEvaluation, ...] = ()
    base_competitive_score: Decimal | None = None
    individual_achievement_points: Decimal | None = None
    effective_competitive_score: Decimal | None = None
    source_gaps: tuple[ShortText, ...] = ()


class AdmissionDecisionResult(ContractModel):
    """Legal eligibility plus optional individual-achievement score composition."""

    program_id: ProgramId
    admission_year: EducationYear
    status: EligibilityStatus
    route: AdmissionRoute | None = None
    eligibility: AdmissionEligibilityResult | None = None
    individual_achievements: IndividualAchievementBreakdown | None = None
    base_competitive_score: Decimal | None = None
    individual_achievement_points: Decimal | None = None
    effective_competitive_score: Decimal | None = None
    competitive_score: EffectiveCompetitiveScore | None = None
    source_gaps: tuple[ShortText, ...] = ()


__all__ = [
    "AdmissionBenefitEvaluation",
    "AdmissionBenefitEvidence",
    "AdmissionDecisionResult",
    "AdmissionEligibilityResult",
    "EligibilityStatus",
    "IndividualAchievementBreakdown",
    "IndividualAchievementEvaluation",
    "IndividualAchievementStatus",
]
