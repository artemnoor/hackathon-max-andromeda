"""Strict HTTP schemas for the Admission Fit calculation contract."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from typing import Annotated

from pydantic import BeforeValidator, Field

from andromeda.modules.admission_fit.contracts.public import (
    AdmissionFitBreakdown,
    AdmissionFitDataQuality,
    AdmissionFitMetric,
    AdmissionFitReason,
    AdmissionFitResult,
    AdmissionFitRequest,
    ApplicantAdmissionProfile,
    ApplicantSubjectScore,
)
from andromeda.modules.admission_fit.contracts.public import (
    AdmissionFitMetricStatus,
    AdmissionFitReasonKind,
    AdmissionFitStatus,
)
from andromeda.modules.admissions.contracts.public import AdmissionProvenance, FundingType, StudyForm

from .admissions import AdmissionProvenanceResponse
from .common import ApiModel


def _decimal_from_json(value: object) -> object:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            return value
    return value


JsonScore = Annotated[
    Decimal,
    BeforeValidator(_decimal_from_json),
    Field(strict=True, ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2),
]


class ApplicantSubjectScoreRequest(ApiModel):
    subject: str = Field(min_length=1, max_length=512)
    score: JsonScore


class ApplicantAdmissionProfileRequest(ApiModel):
    version: Literal[1] = 1
    scores: list[ApplicantSubjectScoreRequest] = Field(default_factory=list)


class AdmissionFitRequestBody(ApiModel):
    version: Literal[1] = 1
    offering_id: str = Field(min_length=1, max_length=512)
    applicant: ApplicantAdmissionProfileRequest


class AdmissionFitMetricResponse(ApiModel):
    value: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"), max_digits=6, decimal_places=2)
    status: AdmissionFitMetricStatus


class AdmissionFitBreakdownResponse(ApiModel):
    minimum_readiness: AdmissionFitMetricResponse
    passing_readiness: AdmissionFitMetricResponse
    data_completeness: AdmissionFitMetricResponse


class AdmissionFitReasonResponse(ApiModel):
    kind: AdmissionFitReasonKind
    message: str = Field(min_length=1, max_length=512)
    subject: str | None = Field(default=None, min_length=1, max_length=512)
    applicant_score: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2)
    applicant_total_score: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("400"), max_digits=6, decimal_places=2)
    reference_score: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("400"), max_digits=6, decimal_places=2)
    source_name: str | None = Field(default=None, min_length=1, max_length=256)
    provenance: tuple[AdmissionProvenanceResponse, ...] = ()


class AdmissionFitResponse(ApiModel):
    program_id: str
    offering_id: str
    admission_year: int
    study_form: StudyForm | None = None
    funding_type: FundingType | None = None
    status: AdmissionFitStatus
    score: int = Field(ge=0, le=100)
    applicant_total_score: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("400"), max_digits=6, decimal_places=2)
    data_quality: AdmissionFitDataQuality
    breakdown: AdmissionFitBreakdownResponse
    reasons: tuple[AdmissionFitReasonResponse, ...]
    anti_reasons: tuple[AdmissionFitReasonResponse, ...]
    data_gaps: tuple[AdmissionFitReasonResponse, ...]


def admission_fit_request(value: AdmissionFitRequestBody) -> AdmissionFitRequest:
    return AdmissionFitRequest(
        version=value.version,
        offering_id=value.offering_id,
        applicant=ApplicantAdmissionProfile(
            version=value.applicant.version,
            scores=tuple(ApplicantSubjectScore(subject=item.subject, score=item.score) for item in value.applicant.scores),
        ),
    )


def _provenance(value: AdmissionProvenance) -> AdmissionProvenanceResponse:
    return AdmissionProvenanceResponse.model_validate(value.model_dump())


def _metric(value: AdmissionFitMetric) -> AdmissionFitMetricResponse:
    return AdmissionFitMetricResponse(value=value.value, status=value.status)


def _reason(value: AdmissionFitReason) -> AdmissionFitReasonResponse:
    return AdmissionFitReasonResponse(
        kind=value.kind,
        message=value.message,
        subject=value.subject,
        applicant_score=value.applicant_score,
        applicant_total_score=value.applicant_total_score,
        reference_score=value.reference_score,
        source_name=value.source_name,
        provenance=tuple(_provenance(item) for item in value.provenance),
    )


def admission_fit_response(value: AdmissionFitResult) -> AdmissionFitResponse:
    breakdown: AdmissionFitBreakdown = value.breakdown
    return AdmissionFitResponse(
        program_id=value.program_id,
        offering_id=value.offering_id,
        admission_year=value.admission_year,
        study_form=value.study_form,
        funding_type=value.funding_type,
        status=value.status,
        score=value.score,
        applicant_total_score=value.applicant_total_score,
        data_quality=value.data_quality,
        breakdown=AdmissionFitBreakdownResponse(
            minimum_readiness=_metric(breakdown.minimum_readiness),
            passing_readiness=_metric(breakdown.passing_readiness),
            data_completeness=_metric(breakdown.data_completeness),
        ),
        reasons=tuple(_reason(item) for item in value.reasons),
        anti_reasons=tuple(_reason(item) for item in value.anti_reasons),
        data_gaps=tuple(_reason(item) for item in value.data_gaps),
    )


__all__ = [
    "AdmissionFitBreakdownResponse",
    "AdmissionFitMetricResponse",
    "AdmissionFitReasonResponse",
    "AdmissionFitRequestBody",
    "AdmissionFitResponse",
    "ApplicantAdmissionProfileRequest",
    "ApplicantSubjectScoreRequest",
    "admission_fit_request",
    "admission_fit_response",
]
