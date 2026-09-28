"""Typed inputs for evaluating an approved policy-selected benefit set."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    AdmissionBenefitRuleId,
    EducationYear,
    ProgramId,
    SourceHash,
    UniversityId,
)

from .applicant import ApplicantAdmissionFacts
from .results import AdmissionDecisionResult


class ApplicantFactDimension(StrEnum):
    EGE_SCORES = "ege_scores"
    INTERNAL_EXAM_SCORES = "internal_exam_scores"
    OLYMPIAD_ACHIEVEMENTS = "olympiad_achievements"
    INDIVIDUAL_ACHIEVEMENTS = "individual_achievements"
    CONFIRMATION_CATEGORY = "confirmation_category"


class ApplicantAdmissionContext(ContractModel):
    """Explicit, short-lived facts plus dimensions the applicant confirmed complete."""

    facts: ApplicantAdmissionFacts = Field(default_factory=ApplicantAdmissionFacts)
    complete_dimensions: tuple[ApplicantFactDimension, ...] = Field(
        default=(), max_length=5
    )

    @model_validator(mode="after")
    def dimensions_are_unique(self) -> ApplicantAdmissionContext:
        if len(self.complete_dimensions) != len(set(self.complete_dimensions)):
            raise ValueError("applicant fact completeness dimensions must be unique")
        return self


class AdmissionBenefitPolicyRuleRef(ContractModel):
    rule_id: AdmissionBenefitRuleId
    revision_hash: SourceHash


class AdmissionBenefitPolicyEvaluationRequest(ContractModel):
    university_id: UniversityId
    program_id: ProgramId
    direction_code: str = Field(min_length=1, max_length=64)
    admission_year: EducationYear
    applicant: ApplicantAdmissionContext
    selected_rules: tuple[AdmissionBenefitPolicyRuleRef, ...] = Field(
        default=(), max_length=64
    )
    selected_individual_policy_id: str | None = Field(default=None, max_length=256)
    selected_individual_policy_hash: SourceHash | None = None

    @model_validator(mode="after")
    def owner_selection_is_unambiguous(self) -> AdmissionBenefitPolicyEvaluationRequest:
        rule_ids = tuple(item.rule_id for item in self.selected_rules)
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("selected admission benefit rules must be unique")
        if (self.selected_individual_policy_id is None) != (
            self.selected_individual_policy_hash is None
        ):
            raise ValueError(
                "individual achievement owner ID and hash must be supplied together"
            )
        if not rule_ids and self.selected_individual_policy_hash is None:
            raise ValueError("policy evaluation needs an exact selected owner revision")
        return self


class AdmissionBenefitPolicyEvaluationStatus(StrEnum):
    EVALUATED = "evaluated"
    INSUFFICIENT_DATA = "insufficient_data"
    UNAVAILABLE = "unavailable"


class AdmissionBenefitPolicyEvaluation(ContractModel):
    status: AdmissionBenefitPolicyEvaluationStatus
    decision: AdmissionDecisionResult | None = None
    missing_input_codes: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def result_matches_status(self) -> AdmissionBenefitPolicyEvaluation:
        if len(self.missing_input_codes) != len(set(self.missing_input_codes)):
            raise ValueError("policy evaluation missing-input codes must be unique")
        if self.status is AdmissionBenefitPolicyEvaluationStatus.EVALUATED:
            if self.decision is None or self.missing_input_codes:
                raise ValueError(
                    "evaluated policy result needs a decision and no missing inputs"
                )
        elif self.status is AdmissionBenefitPolicyEvaluationStatus.INSUFFICIENT_DATA:
            if not self.missing_input_codes:
                raise ValueError(
                    "insufficient policy result must identify missing inputs"
                )
        elif self.decision is not None or not self.missing_input_codes:
            raise ValueError("unavailable policy result needs a reason and no decision")
        return self


__all__ = [
    "AdmissionBenefitPolicyEvaluation",
    "AdmissionBenefitPolicyEvaluationRequest",
    "AdmissionBenefitPolicyEvaluationStatus",
    "AdmissionBenefitPolicyRuleRef",
    "ApplicantAdmissionContext",
    "ApplicantFactDimension",
]
