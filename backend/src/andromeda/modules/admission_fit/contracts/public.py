"""Stable public contracts of the Admission Fit module."""

from __future__ import annotations

from typing import Protocol

from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.shared.contracts.ids import EducationYear, ProgramId

from ..domain.entities import ApplicantAdmissionProfile, ApplicantSubjectScore
from .requests import AdmissionFitRequest, BatchAdmissionFitRequest
from .results import (
    AdmissionFitBreakdown,
    AdmissionFitDataQuality,
    AdmissionFitMetric,
    AdmissionFitMetricStatus,
    AdmissionFitReason,
    AdmissionFitReasonKind,
    AdmissionFitResult,
    AdmissionFitStatus,
    BatchAdmissionFitOutcome,
    BatchAdmissionFitResult,
)

__all__ = [
    "AdmissionFitBatchEvaluator",
    "AdmissionFitBreakdown",
    "AdmissionFitDataQuality",
    "AdmissionFitMetric",
    "AdmissionFitMetricStatus",
    "AdmissionFitReason",
    "AdmissionFitReasonKind",
    "AdmissionFitRequest",
    "AdmissionFitResult",
    "AdmissionFitSearchGateway",
    "AdmissionFitStatus",
    "ApplicantAdmissionProfile",
    "ApplicantSubjectScore",
    "BatchAdmissionFitOutcome",
    "BatchAdmissionFitRequest",
    "BatchAdmissionFitResult",
]


class AdmissionFitBatchEvaluator(Protocol):
    """Public one-call evaluator consumed by candidate orchestration."""

    def evaluate_batch(self, request: BatchAdmissionFitRequest) -> BatchAdmissionFitResult: ...


class AdmissionFitSearchGateway(Protocol):
    """Bulk evaluation and source-backed offering discovery for assistant queries."""

    def evaluate_batches(self, requests: tuple[BatchAdmissionFitRequest, ...]) -> BatchAdmissionFitResult: ...

    def latest_published_year(
        self,
        program_ids: tuple[ProgramId, ...],
        *,
        study_form: StudyForm,
        funding_type: FundingType,
    ) -> EducationYear | None: ...
