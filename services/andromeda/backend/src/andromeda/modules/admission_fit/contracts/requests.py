"""Input contracts for Admission Fit."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EducationYear, NonEmptyText, ProgramId
from andromeda.modules.admissions.contracts.public import FundingType, StudyForm

from ..domain.entities import ApplicantAdmissionProfile
from ..domain.subject_identity import normalize_subject_name


class AdmissionFitRequest(ContractModel):
    """Application request for one explicitly selected admission offering."""

    version: Literal[1] = 1
    offering_id: NonEmptyText
    applicant: ApplicantAdmissionProfile

    @classmethod
    def from_parts(cls, offering_id: str, applicant: ApplicantAdmissionProfile) -> "AdmissionFitRequest":
        return cls(offering_id=offering_id, applicant=applicant)


class BatchAdmissionFitRequest(ContractModel):
    """Admission Fit facts for a bounded set of candidate programs."""

    version: Literal[1] = 1
    program_ids: tuple[ProgramId, ...] = Field(min_length=1, max_length=50)
    applicant: ApplicantAdmissionProfile
    admission_year: EducationYear | None = None
    study_form: StudyForm | None = None
    funding_type: FundingType | None = None

    @model_validator(mode="after")
    def validate_program_ids(self) -> "BatchAdmissionFitRequest":
        if len(self.program_ids) != len(set(self.program_ids)):
            raise ValueError("batch admission programs must be unique")
        return self


def normalized_applicant_subjects(profile: ApplicantAdmissionProfile) -> tuple[str, ...]:
    """Return canonical keys for adapter/UI diagnostics without exposing internals."""

    return tuple(normalize_subject_name(item.subject) for item in profile.scores)


__all__ = ["AdmissionFitRequest", "BatchAdmissionFitRequest", "normalized_applicant_subjects"]
