"""Output contracts for Admission Fit."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.modules.admissions.contracts.public import (
    AdmissionProvenance,
    FundingType,
    StudyForm,
)
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EducationYear, NonEmptyText, ProgramId

ZERO = Decimal(0)
ONE_HUNDRED = Decimal(100)


class AdmissionFitStatus(StrEnum):
    REALISTIC = "realistic"
    BORDERLINE = "borderline"
    UNLIKELY = "unlikely"
    INSUFFICIENT_DATA = "insufficient_data"


class AdmissionFitDataQuality(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class AdmissionFitMetricStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    NOT_AVAILABLE = "not_available"


class AdmissionFitMetric(ContractModel):
    """One explainable percentage component of the final score."""

    value: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=ONE_HUNDRED, max_digits=6, decimal_places=2)
    status: AdmissionFitMetricStatus


class AdmissionFitBreakdown(ContractModel):
    minimum_readiness: AdmissionFitMetric
    passing_readiness: AdmissionFitMetric
    data_completeness: AdmissionFitMetric


class AdmissionFitReasonKind(StrEnum):
    FIT = "fit"
    ANTI_FIT = "anti_fit"
    DATA_GAP = "data_gap"


class AdmissionFitReason(ContractModel):
    """A user-facing explanation backed by one or more admission facts."""

    kind: AdmissionFitReasonKind
    message: NonEmptyText
    subject: NonEmptyText | None = None
    applicant_score: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=ONE_HUNDRED, max_digits=5, decimal_places=2)
    applicant_total_score: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=Decimal(400), max_digits=6, decimal_places=2)
    reference_score: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=Decimal(400), max_digits=6, decimal_places=2)
    source_name: NonEmptyText | None = None
    provenance: tuple[AdmissionProvenance, ...] = ()


class AdmissionFitResult(ContractModel):
    """Admission Fit result; deliberately independent from Content Fit."""

    program_id: ProgramId
    offering_id: NonEmptyText
    admission_year: EducationYear
    study_form: StudyForm | None = None
    funding_type: FundingType | None = None
    status: AdmissionFitStatus
    score: int = Field(strict=True, ge=0, le=100)
    applicant_total_score: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=Decimal(400), max_digits=6, decimal_places=2)
    data_quality: AdmissionFitDataQuality
    breakdown: AdmissionFitBreakdown
    reasons: tuple[AdmissionFitReason, ...] = ()
    anti_reasons: tuple[AdmissionFitReason, ...] = ()
    data_gaps: tuple[AdmissionFitReason, ...] = ()


class BatchAdmissionFitOutcome(ContractModel):
    """One source-backed or explicitly unavailable batch result."""

    program_id: ProgramId
    status: AdmissionFitStatus
    result: AdmissionFitResult | None = None
    data_gaps: tuple[AdmissionFitReason, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_result_identity(self) -> BatchAdmissionFitOutcome:
        if self.result is not None:
            if self.result.program_id != self.program_id or self.result.status is not self.status:
                raise ValueError("batch outcome result must match program and status")
        elif self.status is not AdmissionFitStatus.INSUFFICIENT_DATA:
            raise ValueError("missing batch result must be insufficient_data")
        return self


class BatchAdmissionFitResult(ContractModel):
    """Deterministic per-program Admission Fit outcomes, never a global score."""

    by_program_id: dict[ProgramId, BatchAdmissionFitOutcome] = Field(default_factory=dict, max_length=5000)

    @model_validator(mode="after")
    def validate_index(self) -> BatchAdmissionFitResult:
        for program_id, outcome in self.by_program_id.items():
            if program_id != outcome.program_id:
                raise ValueError("batch result index must match outcome program id")
        return self


__all__ = [
    "AdmissionFitBreakdown",
    "AdmissionFitDataQuality",
    "AdmissionFitMetric",
    "AdmissionFitMetricStatus",
    "AdmissionFitReason",
    "AdmissionFitReasonKind",
    "AdmissionFitResult",
    "AdmissionFitStatus",
    "BatchAdmissionFitOutcome",
    "BatchAdmissionFitResult",
]
