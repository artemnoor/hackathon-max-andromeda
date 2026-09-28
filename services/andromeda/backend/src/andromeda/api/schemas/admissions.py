"""Strict HTTP schemas for the program admissions read contract."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field, HttpUrl

from andromeda.modules.admissions.contracts.public import (
    AdmissionOffering,
    AdmissionCompetitionType,
    AdmissionProvenance,
    ExamRequirement,
    PassingScore,
    PassingScoreStatus,
    ProgramAdmissions,
    Quota,
    TuitionCost,
)
from andromeda.modules.admissions.contracts.public import FundingType, PassingScoreType, QuotaType, StudyForm, AdmissionScope
from andromeda.modules.admissions.contracts.results import ProgramAdmissionsResult

from .common import ApiModel, ProgramSummaryResponse


class AdmissionProvenanceResponse(ApiModel):
    source_kind: str
    source_url: HttpUrl
    captured_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str | None = None
    source_name: str | None = None
    university_id: str | None = None
    run_id: str | None = None
    field: str | None = None
    record_key: str | None = None
    inferred: bool = False


class ExamRequirementResponse(ApiModel):
    subject: str
    source_name: str
    minimum_score: Decimal | None = None
    is_choice: bool
    is_required: bool
    provenance: AdmissionProvenanceResponse


class QuotaResponse(ApiModel):
    quota_type: QuotaType
    source_name: str
    places: int
    provenance: AdmissionProvenanceResponse


class PassingScoreResponse(ApiModel):
    score_type: PassingScoreType
    competition_type: AdmissionCompetitionType = AdmissionCompetitionType.GENERAL
    status: PassingScoreStatus = PassingScoreStatus.NUMERIC
    score: Decimal | None = None
    provenance: AdmissionProvenanceResponse


class TuitionCostResponse(ApiModel):
    amount: Decimal
    currency: str
    academic_year: str | None = None
    period: str | None = None
    study_form: StudyForm | None = None
    is_discounted: bool
    provenance: AdmissionProvenanceResponse


class AdmissionOfferingResponse(ApiModel):
    id: str
    admission_year: int
    study_form: StudyForm | None = None
    funding_type: FundingType | None = None
    scope: AdmissionScope
    places: int | None = None
    exams: tuple[ExamRequirementResponse, ...]
    quotas: tuple[QuotaResponse, ...]
    passing_scores: tuple[PassingScoreResponse, ...]
    tuition: tuple[TuitionCostResponse, ...]
    provenance: tuple[AdmissionProvenanceResponse, ...]


class ProgramAdmissionsResponse(ApiModel):
    program: ProgramSummaryResponse
    program_id: str
    offerings: tuple[AdmissionOfferingResponse, ...]


def _provenance(value: AdmissionProvenance) -> AdmissionProvenanceResponse:
    return AdmissionProvenanceResponse.model_validate(value.model_dump())


def _exam(value: ExamRequirement) -> ExamRequirementResponse:
    return ExamRequirementResponse(
        subject=value.subject,
        source_name=value.source_name,
        minimum_score=value.minimum_score,
        is_choice=value.is_choice,
        is_required=value.is_required,
        provenance=_provenance(value.provenance),
    )


def _quota(value: Quota) -> QuotaResponse:
    return QuotaResponse(quota_type=value.quota_type, source_name=value.source_name, places=value.places, provenance=_provenance(value.provenance))


def _passing(value: PassingScore) -> PassingScoreResponse:
    return PassingScoreResponse(
        score_type=value.score_type,
        competition_type=value.competition_type,
        status=value.status,
        score=value.score,
        provenance=_provenance(value.provenance),
    )


def _tuition(value: TuitionCost) -> TuitionCostResponse:
    return TuitionCostResponse(
        amount=value.amount,
        currency=value.currency,
        academic_year=value.academic_year,
        period=value.period,
        study_form=value.study_form,
        is_discounted=value.is_discounted,
        provenance=_provenance(value.provenance),
    )


def _offering(value: AdmissionOffering) -> AdmissionOfferingResponse:
    return AdmissionOfferingResponse(
        id=value.id,
        admission_year=value.admission_year,
        study_form=value.study_form,
        funding_type=value.funding_type,
        scope=value.scope,
        places=value.places,
        exams=tuple(_exam(item) for item in value.exams),
        quotas=tuple(_quota(item) for item in value.quotas),
        passing_scores=tuple(_passing(item) for item in value.passing_scores),
        tuition=tuple(_tuition(item) for item in value.tuition),
        provenance=tuple(_provenance(item) for item in value.provenance),
    )


def admissions_response(result: ProgramAdmissionsResult) -> ProgramAdmissionsResponse:
    return ProgramAdmissionsResponse(
        program=ProgramSummaryResponse.model_validate(result.program.model_dump()),
        program_id=result.program_id,
        offerings=tuple(_offering(item) for item in result.offerings),
    )


__all__ = ["ProgramAdmissionsResponse", "admissions_response"]
