"""Applicant-provided admission facts, separate from Admission Fit profile."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    EducationYear,
    NonEmptyText,
    OlympiadId,
    OlympiadProfileId,
)

from .public import ConfirmationApplicantCategory, OlympiadResultType


class ApplicantExamScore(ContractModel):
    subject: NonEmptyText
    score: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2)


class ApplicantInternalExamScore(ContractModel):
    """Applicant result from a university internal entrance exam."""

    subject: NonEmptyText
    score: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2)


class ApplicantOlympiadAchievement(ContractModel):
    olympiad_id: OlympiadId
    olympiad_profile_id: OlympiadProfileId | None = None
    result_year: EducationYear
    result_type: OlympiadResultType
    confirmation_subject: NonEmptyText | None = None
    grade_or_class: NonEmptyText | None = None
    evidence_reference: NonEmptyText | None = None


class ApplicantIndividualAchievement(ContractModel):
    achievement_code: NonEmptyText
    year: EducationYear | None = None
    details: NonEmptyText | None = None
    evidence_reference: NonEmptyText | None = None


class ApplicantAdmissionFacts(ContractModel):
    ege_scores: tuple[ApplicantExamScore, ...] = ()
    internal_exam_scores: tuple[ApplicantInternalExamScore, ...] = ()
    olympiad_achievements: tuple[ApplicantOlympiadAchievement, ...] = ()
    individual_achievements: tuple[ApplicantIndividualAchievement, ...] = ()
    confirmation_category: ConfirmationApplicantCategory | None = None

    @model_validator(mode="after")
    def validate_exam_subjects(self) -> ApplicantAdmissionFacts:
        subjects = tuple(score.subject.casefold() for score in self.ege_scores)
        if len(subjects) != len(set(subjects)):
            raise ValueError("duplicate_exam_subject: applicant facts contain duplicate exam subject")
        return self


__all__ = [
    "ApplicantAdmissionFacts",
    "ApplicantExamScore",
    "ApplicantIndividualAchievement",
    "ApplicantInternalExamScore",
    "ApplicantOlympiadAchievement",
]
