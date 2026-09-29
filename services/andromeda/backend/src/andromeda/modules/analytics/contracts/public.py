"""Channel-neutral contracts for persisted program analytical projections."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.modules.admissions.contracts.public import AdmissionOffering
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.semantic.contracts.public import SemanticClassificationEvidence
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    CurriculumItemId,
    DirectionId,
    NonEmptyText,
    ProgramCode,
    ProgramId,
    SemanticFeatureCode,
    SemanticFeatureId,
    SemanticVersion,
    SourceHash,
    UniversityId,
)
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference
from andromeda.shared.contracts.versions import ANALYTICS_PROJECTION_SCHEMA_VERSION

from ..domain.basis import MetricBasis
from ..domain.projection import distribution_is_complete
from .activity import ACTIVITY_SIGNAL_WEIGHTS as _ACTIVITY_SIGNAL_WEIGHTS
from .activity import ActivitySignalCode

ACTIVITY_SIGNAL_WEIGHTS = _ACTIVITY_SIGNAL_WEIGHTS


class ProjectionDataQualityStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"
    UNAVAILABLE = "unavailable"


class ProjectionMaterializationStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    FAILED = "failed"


class ProjectionRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ProgramProjectionRun(ContractModel):
    id: str
    ingest_run_id: str | None = None
    university_id: UniversityId
    projection_version: SemanticVersion
    semantic_version: SemanticVersion | None = None
    classifier_version: SemanticVersion | None = None
    input_hash: str
    status: ProjectionRunStatus
    affected_program_count: int = Field(strict=True, ge=0)
    refreshed_program_count: int = Field(strict=True, ge=0)
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class WorkloadSummary(ContractModel):
    total_hours: int | None = Field(default=None, strict=True, ge=0)
    total_credits: Decimal | None = Field(default=None, strict=True, ge=Decimal("0"))
    total_workload: Decimal | None = Field(default=None, strict=True, ge=Decimal("0"))
    basis: MetricBasis

    @model_validator(mode="after")
    def validate_basis(self) -> WorkloadSummary:
        if self.basis is MetricBasis.HOURS and self.total_workload is not None and self.total_hours is not None:
            if self.total_workload != Decimal(self.total_hours):
                raise ValueError("hours basis must use total_hours as total_workload")
        if self.basis is MetricBasis.CREDITS and self.total_workload is not None and self.total_credits is not None:
            if self.total_workload != self.total_credits:
                raise ValueError("credits basis must use total_credits as total_workload")
        return self


class ProjectionMetric(ContractModel):
    """One explainable metric observation; absent data remains absent."""

    code: SemanticFeatureCode
    value: Decimal | None = Field(default=None, strict=True, ge=Decimal("0"))
    unit: NonEmptyText = "share"
    basis: MetricBasis | None = None
    coverage: Decimal = Field(default=Decimal("0"), strict=True, ge=Decimal("0"), le=Decimal("1"))
    confidence: Decimal = Field(default=Decimal("0"), strict=True, ge=Decimal("0"), le=Decimal("1"))
    status: ProjectionDataQualityStatus = ProjectionDataQualityStatus.UNAVAILABLE
    provenance: tuple[SourceAttribution, ...] = Field(default=(), max_length=100)
    source_gaps: tuple[SourceGapReference, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_availability(self) -> ProjectionMetric:
        if self.value is not None and self.status is ProjectionDataQualityStatus.UNAVAILABLE:
            raise ValueError("a metric with a value cannot be unavailable")
        if self.status is ProjectionDataQualityStatus.AVAILABLE and self.value is None:
            raise ValueError("an available metric must have a value")
        return self


class ProjectionTimeline(ContractModel):
    by_semester: dict[str, Decimal] = Field(default_factory=dict)
    by_course_year: dict[str, Decimal] = Field(default_factory=dict)
    feature_by_semester: dict[str, dict[str, Decimal]] = Field(default_factory=dict)
    first_feature_semester: dict[str, int] = Field(default_factory=dict)


class AssessmentSummary(ContractModel):
    exam_count: int | None = Field(default=None, strict=True, ge=0)
    credit_count: int | None = Field(default=None, strict=True, ge=0)
    graded_count: int | None = Field(default=None, strict=True, ge=0)
    unknown_count: int | None = Field(default=None, strict=True, ge=0)


class ProjectionDataQuality(ContractModel):
    status: ProjectionDataQualityStatus
    coverage: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    confidence: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    freshness_at: datetime | None = None
    semantic_version: SemanticVersion | None = None
    classifier_version: SemanticVersion | None = None


class ProjectionMetricEvidence(ContractModel):
    program_id: ProgramId
    metric_code: SemanticFeatureCode
    schema_version: SemanticVersion
    curriculum_item_id: CurriculumItemId
    feature_id: SemanticFeatureId
    contribution: Decimal | None = Field(default=None, strict=True, ge=Decimal("0"))
    source_hash: SourceHash | None = None
    evidence: tuple[SemanticClassificationEvidence, ...] = Field(default=(), max_length=16)
    provenance: tuple[SourceAttribution, ...] = Field(default=(), max_length=20)


class ProgramProjection(ContractModel):
    """Reusable derived view of one program, independent from proftest."""

    schema_version: SemanticVersion = ANALYTICS_PROJECTION_SCHEMA_VERSION
    program_id: ProgramId
    university_id: UniversityId
    direction_id: DirectionId
    program_code: ProgramCode
    program_name: NonEmptyText
    workload: WorkloadSummary
    academic_areas: dict[DisciplineAreaCode, Decimal] = Field(default_factory=dict)
    semantic_features: dict[SemanticFeatureCode, ProjectionMetric] = Field(default_factory=dict)
    timeline: ProjectionTimeline = Field(default_factory=ProjectionTimeline)
    activity_signals: dict[ActivitySignalCode, Decimal] = Field(default_factory=dict)
    assessment: AssessmentSummary = Field(default_factory=AssessmentSummary)
    admission_offerings: tuple[AdmissionOffering, ...] = Field(default=(), max_length=1000)
    distinctive_subjects: tuple[NonEmptyText, ...] = Field(default=(), max_length=100)
    quality: ProjectionDataQuality
    provenance: tuple[SourceAttribution, ...] = Field(default=(), max_length=100)
    source_gaps: tuple[SourceGapReference, ...] = Field(default=(), max_length=100)
    ingest_run_id: str | None = None
    projection_run_id: str | None = None
    input_hash: str | None = None
    materialization_status: ProjectionMaterializationStatus = ProjectionMaterializationStatus.ACTIVE

    @model_validator(mode="after")
    def validate_distributions(self) -> ProgramProjection:
        if self.workload.total_workload is not None and self.workload.total_workload > Decimal("0"):
            if self.academic_areas and not distribution_is_complete(self.academic_areas):
                raise ValueError("academic_areas must sum to one when present")
            if self.activity_signals and not distribution_is_complete(self.activity_signals):
                raise ValueError("activity_signals must sum to one when present")
        return self


__all__ = [
    "ACTIVITY_SIGNAL_WEIGHTS",
    "ActivitySignalCode",
    "AssessmentSummary",
    "ProgramProjection",
    "ProgramProjectionRun",
    "ProjectionBuild",
    "ProjectionDataQuality",
    "ProjectionDataQualityStatus",
    "ProjectionMaterializationStatus",
    "ProjectionMetric",
    "ProjectionMetricEvidence",
    "ProjectionTimeline",
    "ProjectionRunStatus",
    "WorkloadSummary",
]


class ProjectionBuild(ContractModel):
    projection: ProgramProjection
    evidence: tuple[ProjectionMetricEvidence, ...] = Field(default=(), max_length=100_000)
