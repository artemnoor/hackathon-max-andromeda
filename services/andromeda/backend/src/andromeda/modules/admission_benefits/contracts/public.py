"""Canonical source-backed admission benefit entities."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.enums import EducationLevel
from andromeda.shared.contracts.ids import (
    AdmissionBenefitRuleId,
    EducationYear,
    IndividualAchievementRuleId,
    NonEmptyText,
    OlympiadId,
    OlympiadProfileId,
    UniversityId,
)

from .policy import BenefitConditionKind, BenefitScope
from .provenance import BenefitProvenance
from .status import BenefitPolicyVersion, RuleDataStatus

ZERO = Decimal("0")
HUNDRED = Decimal("100")


class BenefitType(StrEnum):
    BVI = "bvi"
    ONE_HUNDRED_POINTS = "one_hundred_points"
    MAX_INTERNAL_EXAM_SCORE = "max_internal_exam_score"
    SPECIAL_RIGHT = "special_right"
    PREFERENTIAL_RIGHT = "preferential_right"
    SPECIAL_QUOTA = "special_quota"
    SEPARATE_QUOTA = "separate_quota"
    TARGETED_ROUTE = "targeted_route"
    OTHER_REVIEW_REQUIRED = "other_review_required"


class AdmissionRoute(StrEnum):
    OLYMPIAD = "olympiad"
    VOSH = "vosh"
    INTERNATIONAL = "international"
    SPECIAL_RIGHT = "special_right"
    PREFERENTIAL_RIGHT = "preferential_right"
    SPECIAL_QUOTA = "special_quota"
    SEPARATE_QUOTA = "separate_quota"
    TARGETED = "targeted"
    OTHER = "other"


class OlympiadResultType(StrEnum):
    WINNER = "winner"
    PRIZE_WINNER = "prize_winner"
    TEAM_MEMBER = "team_member"


class ConfirmationRequirement(StrEnum):
    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"


class ConfirmationExamKind(StrEnum):
    EGE = "ege"
    INTERNAL_EXAM = "internal_exam"
    OTHER = "other"
    UNKNOWN = "unknown"


class ConfirmationApplicantCategory(StrEnum):
    STANDARD = "standard"
    TERRITORIAL_EXCEPTION = "territorial_exception"
    UNKNOWN = "unknown"


class ConfirmationSubjectRule(ContractModel):
    subject: NonEmptyText
    minimum_score: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=HUNDRED, max_digits=5, decimal_places=2)
    exam_kind: ConfirmationExamKind = ConfirmationExamKind.UNKNOWN
    applicant_category: ConfirmationApplicantCategory | None = None
    source_text: NonEmptyText


class ValidityPolicy(ContractModel):
    """Source-backed validity constraints; candidate-year evaluation is separate."""

    valid_from_result_year: EducationYear | None = None
    valid_until_result_year: EducationYear | None = None
    max_age_years: int | None = Field(default=None, strict=True, ge=0, le=20)
    source_text: NonEmptyText

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if (
            self.valid_from_result_year is not None
            and self.valid_until_result_year is not None
            and self.valid_from_result_year > self.valid_until_result_year
        ):
            raise ValueError("validity_range_invalid: result-year lower bound exceeds upper bound")
        return self


class BenefitCondition(ContractModel):
    kind: BenefitConditionKind
    source_text: NonEmptyText
    normalized_value: NonEmptyText | None = None
    provenance: BenefitProvenance | None = None


class Olympiad(ContractModel):
    id: OlympiadId
    official_name: NonEmptyText
    organizer: NonEmptyText | None = None
    rsosh_level: int | None = Field(default=None, strict=True, ge=1, le=3)
    admission_year: EducationYear
    provenance: tuple[BenefitProvenance, ...] = Field(min_length=1)


class OlympiadProfileSubject(ContractModel):
    subject: NonEmptyText
    source_text: NonEmptyText


class OlympiadProfile(ContractModel):
    id: OlympiadProfileId
    olympiad_id: OlympiadId
    profile_name: NonEmptyText
    corresponding_subjects: tuple[OlympiadProfileSubject, ...] = Field(min_length=1)
    admission_year: EducationYear
    provenance: tuple[BenefitProvenance, ...] = Field(min_length=1)


class AdmissionBenefitRule(ContractModel):
    id: AdmissionBenefitRuleId
    university_id: UniversityId
    admission_year: EducationYear
    education_level: EducationLevel | None = None
    route: AdmissionRoute
    benefit_type: BenefitType
    olympiad_id: OlympiadId | None = None
    olympiad_profile_id: OlympiadProfileId | None = None
    result_type: OlympiadResultType | None = None
    scope: BenefitScope
    confirmation_requirement: ConfirmationRequirement = ConfirmationRequirement.UNKNOWN
    confirmation_subjects: tuple[ConfirmationSubjectRule, ...] = ()
    validity: ValidityPolicy
    target_subject: NonEmptyText | None = None
    points: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=HUNDRED, max_digits=5, decimal_places=2)
    conditions: tuple[BenefitCondition, ...] = ()
    source_text: NonEmptyText
    status: RuleDataStatus = RuleDataStatus.ACTIVE
    policy_version: BenefitPolicyVersion
    provenance: BenefitProvenance

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        if self.route in {AdmissionRoute.OLYMPIAD, AdmissionRoute.VOSH, AdmissionRoute.INTERNATIONAL}:
            if self.olympiad_id is None or self.result_type is None:
                raise ValueError("unknown_result_type: olympiad rules require olympiad and result type")
        elif self.olympiad_id is not None or self.olympiad_profile_id is not None or self.result_type is not None:
            raise ValueError("olympiad_identity_invalid: non-olympiad route cannot carry olympiad identity")
        if self.olympiad_profile_id is not None and self.olympiad_id is None:
            raise ValueError("olympiad_identity_invalid: profile requires an olympiad")
        if self.confirmation_requirement is ConfirmationRequirement.REQUIRED and not self.confirmation_subjects:
            raise ValueError("confirmation_subject_missing: required confirmation needs a subject")
        if self.benefit_type is BenefitType.BVI:
            if self.points is not None:
                raise ValueError("bvi_numeric_value_forbidden: BVI cannot carry a numeric score")
            if self.target_subject is not None:
                raise ValueError("bvi_subject_forbidden: BVI cannot carry a 100-point subject")
        if self.benefit_type is BenefitType.ONE_HUNDRED_POINTS:
            if self.target_subject is None:
                raise ValueError("hundred_point_subject_missing: 100-point rule needs a target subject")
            if self.points != HUNDRED:
                raise ValueError("hundred_point_value_invalid: 100-point rule must carry exactly 100")
        if self.status is RuleDataStatus.ACTIVE and self.provenance is None:
            raise ValueError("missing_provenance: active rule needs source evidence")
        return self


class AchievementCombinationPolicy(StrEnum):
    ADDITIVE = "additive"
    MAX_ONLY = "max_only"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"
    NOT_COMBINABLE = "not_combinable"
    UNKNOWN = "unknown"


class IndividualAchievementRule(ContractModel):
    id: IndividualAchievementRuleId
    university_id: UniversityId
    admission_year: EducationYear
    education_level: EducationLevel | None = None
    achievement_code: NonEmptyText
    category: NonEmptyText
    official_name: NonEmptyText
    description: NonEmptyText | None = None
    points: Decimal = Field(strict=True, ge=ZERO, le=HUNDRED, max_digits=5, decimal_places=2)
    category_cap: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=HUNDRED, max_digits=5, decimal_places=2)
    combination_group: NonEmptyText | None = None
    combination_policy: AchievementCombinationPolicy = AchievementCombinationPolicy.UNKNOWN
    required_document: NonEmptyText | None = None
    conditions: tuple[BenefitCondition, ...] = ()
    source_text: NonEmptyText
    status: RuleDataStatus = RuleDataStatus.ACTIVE
    policy_version: BenefitPolicyVersion
    provenance: BenefitProvenance

    @model_validator(mode="after")
    def validate_combination(self) -> Self:
        if self.combination_policy in {
            AchievementCombinationPolicy.MAX_ONLY,
            AchievementCombinationPolicy.MUTUALLY_EXCLUSIVE,
            AchievementCombinationPolicy.NOT_COMBINABLE,
        } and self.combination_group is None:
            raise ValueError("combination_group_missing: non-additive achievement needs a group")
        if self.category_cap is not None and self.points > self.category_cap:
            raise ValueError("category_cap_invalid: rule points exceed category cap")
        return self


class IndividualAchievementPolicy(ContractModel):
    university_id: UniversityId
    admission_year: EducationYear
    education_level: EducationLevel | None = None
    global_max_points: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=HUNDRED, max_digits=5, decimal_places=2)
    default_combination_policy: AchievementCombinationPolicy = AchievementCombinationPolicy.UNKNOWN
    rules: tuple[IndividualAchievementRule, ...] = Field(min_length=1)
    source_text: NonEmptyText
    status: RuleDataStatus = RuleDataStatus.ACTIVE
    policy_version: BenefitPolicyVersion
    provenance: BenefitProvenance

    @model_validator(mode="after")
    def validate_rules(self) -> Self:
        if any(rule.university_id != self.university_id for rule in self.rules):
            raise ValueError("achievement_university_mismatch: all rules must belong to policy university")
        if any(rule.admission_year != self.admission_year for rule in self.rules):
            raise ValueError("achievement_year_mismatch: all rules must belong to policy year")
        if self.global_max_points is not None and any(rule.points > self.global_max_points for rule in self.rules):
            raise ValueError("global_cap_invalid: rule points exceed global cap")
        return self


__all__ = [
    "AchievementCombinationPolicy",
    "AdmissionBenefitRule",
    "AdmissionRoute",
    "BenefitCondition",
    "BenefitType",
    "ConfirmationApplicantCategory",
    "ConfirmationExamKind",
    "ConfirmationRequirement",
    "ConfirmationSubjectRule",
    "IndividualAchievementPolicy",
    "IndividualAchievementRule",
    "Olympiad",
    "OlympiadProfile",
    "OlympiadProfileSubject",
    "OlympiadResultType",
    "ValidityPolicy",
]
