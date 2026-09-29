"""Transport- and storage-neutral lifecycle contracts for derived analytics."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from andromeda.modules.admissions.contracts.public import ProgramAdmissions
from andromeda.modules.curricula.contracts.public import Curriculum
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    IngestRunId,
    ProgramId,
    SemanticVersion,
    SourceHash,
    UniversityId,
)

from andromeda.modules.analytics.contracts.public import (
    ACTIVITY_SIGNAL_WEIGHTS,
    ActivitySignalCode,
    AssessmentSummary,
    ProgramProjection,
    ProjectionBuild,
    ProjectionDataQuality,
    ProjectionDataQualityStatus,
    ProjectionMetric,
    ProjectionMetricEvidence,
    ProjectionTimeline,
    WorkloadSummary,
)

from .fingerprint import ActivityCode, CurriculumEvidence, DistinctiveSubject, ProgramFingerprint


class DerivedRefreshStatus(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class DerivedRefreshRequest(ContractModel):
    """Canonical data handed to post-commit derived processing.

    The request contains already normalized contracts, never raw source bodies or
    transport state. Keeping the snapshot here makes the post-commit port usable
    by both the ingestion runner and an explicit rebuild command without importing
    the ingestion package into the subject module.
    """

    ingest_run_id: IngestRunId
    university_id: UniversityId
    affected_program_ids: tuple[ProgramId, ...] = Field(min_length=1, max_length=100_000)
    source_hashes: tuple[SourceHash, ...] = Field(default=(), max_length=1000)
    semantic_version: SemanticVersion
    classifier_version: SemanticVersion
    projection_version: SemanticVersion
    programs: tuple[Program, ...] = Field(min_length=1, max_length=100_000)
    disciplines: tuple[Discipline, ...] = Field(min_length=1, max_length=100_000)
    curricula: tuple[Curriculum, ...] = Field(default=(), max_length=100_000)
    admissions: tuple[ProgramAdmissions, ...] = Field(default=(), max_length=100_000)


class DerivedRefreshOutcome(ContractModel):
    ingest_run_id: IngestRunId
    university_id: UniversityId
    status: DerivedRefreshStatus
    affected_program_count: int = Field(strict=True, ge=0)
    refreshed_program_count: int = Field(strict=True, ge=0)
    semantic_run_id: str | None = Field(default=None, max_length=128)
    input_hash: str | None = Field(default=None, max_length=128)
    semantic_version: SemanticVersion
    classifier_version: SemanticVersion
    projection_version: SemanticVersion
    started_at: datetime
    finished_at: datetime | None = None
    failure_code: str | None = Field(default=None, max_length=64)
    recovery_reason: str | None = Field(default=None, max_length=256)


class DerivedRefreshPort(Protocol):
    def refresh(self, request: DerivedRefreshRequest) -> DerivedRefreshOutcome:
        """Refresh semantic assignments and analytical projections after commit."""


__all__ = [
    "ActivityCode",
    "ACTIVITY_SIGNAL_WEIGHTS",
    "ActivitySignalCode",
    "AssessmentSummary",
    "CurriculumEvidence",
    "DistinctiveSubject",
    "DerivedRefreshOutcome",
    "DerivedRefreshPort",
    "DerivedRefreshRequest",
    "DerivedRefreshStatus",
    "ProgramFingerprint",
    "ProgramProjection",
    "ProjectionBuild",
    "ProjectionDataQuality",
    "ProjectionDataQualityStatus",
    "ProjectionMetric",
    "ProjectionMetricEvidence",
    "ProjectionTimeline",
    "WorkloadSummary",
]
