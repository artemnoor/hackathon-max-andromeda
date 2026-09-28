from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from andromeda.modules.admin_ops.contracts.public import IngestionRunStatus
from andromeda.modules.admin_ops.contracts.results import IngestionRunDetailResult, IngestionRunListResult
from andromeda.modules.admin_ops.domain.entities import IngestionRunDetail, IngestionRunSummary
from andromeda.shared.contracts.ids import IngestRunId, SourceHash

from .common import ApiModel


class IngestionRunSummaryResponse(ApiModel):
    id: IngestRunId
    status: IngestionRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    source_count: int = Field(strict=True, ge=0)
    program_count: int = Field(strict=True, ge=0)
    curriculum_item_count: int = Field(strict=True, ge=0)
    event_count: int = Field(strict=True, ge=0)
    campus_point_count: int = Field(strict=True, ge=0)
    inserted_count: int = Field(strict=True, ge=0)
    updated_count: int = Field(strict=True, ge=0)
    unchanged_count: int = Field(strict=True, ge=0)
    removed_count: int = Field(strict=True, ge=0)
    error_code: str | None = Field(default=None, min_length=1, max_length=64)
    error_message: str | None = Field(default=None, min_length=1, max_length=512)
    university_id: str | None = None
    duration_ms: int | None = Field(default=None, strict=True, ge=0)
    source_gap_count: int = Field(default=0, strict=True, ge=0)
    critical_gap_count: int = Field(default=0, strict=True, ge=0)
    drift_status: Literal["not_checked", "passed", "rejected"] = "not_checked"
    quality_status: Literal["not_checked", "passed", "degraded", "rejected"] = "not_checked"
    previous_good_run_id: IngestRunId | None = None
    source_profile: str
    source_revision: str
    configuration_version: str
    retry_of_run_id: IngestRunId | None = None
    projection_target: str = "canonical"
    heartbeat_at: datetime | None = None
    projection_status: Literal["not_started", "running", "committed", "reconciled", "failed"] = "not_started"
    recovery_reason: str | None = Field(default=None, min_length=1, max_length=128)


class IngestionRunDetailResponse(IngestionRunSummaryResponse):
    source_hashes: tuple[SourceHash, ...] = ()
    source_kinds: tuple[str, ...] = ()


class IngestionRunListResponse(ApiModel):
    items: tuple[IngestionRunSummaryResponse, ...] = ()
    total: int = Field(strict=True, ge=0)


class IngestionRunDetailEnvelope(ApiModel):
    run: IngestionRunDetailResponse


class IngestionRetryRequestBody(ApiModel):
    source: Literal["bmstu_fixture", "bmstu_live", "hse_fixture", "hse_live"] = "bmstu_fixture"
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=96, pattern=r"^[A-Za-z0-9._:-]+$")
    retry_of_run_id: IngestRunId | None = None


class SourceHealthItemResponse(ApiModel):
    university_id: str
    state: Literal["fresh", "stale", "degraded", "failed"]
    latest_successful_run_id: IngestRunId | None = None
    latest_attempt_run_id: IngestRunId | None = None
    age_seconds: int | None = Field(default=None, strict=True, ge=0)
    source_gap_count: int = Field(strict=True, ge=0)
    critical_gap_count: int = Field(strict=True, ge=0)
    drift_status: Literal["not_checked", "passed", "rejected"]


class SourceHealthResponse(ApiModel):
    items: tuple[SourceHealthItemResponse, ...] = ()


class DecisionAnalyticsFunnelResponse(ApiModel):
    decision_sessions: int = Field(strict=True, ge=0)
    shortlist_started: int = Field(strict=True, ge=0)
    comparison_started: int = Field(strict=True, ge=0)
    comparison_completed: int = Field(strict=True, ge=0)
    suggestion_shown: int = Field(strict=True, ge=0)
    suggestion_accepted: int = Field(strict=True, ge=0)
    final_choice_selected: int = Field(strict=True, ge=0)
    average_shortlist_size: float | None = Field(default=None, strict=True, ge=0, le=20)
    shortlist_conversion_percent: float | None = Field(default=None, strict=True, ge=0, le=100)
    comparison_conversion_percent: float | None = Field(default=None, strict=True, ge=0, le=100)
    final_choice_conversion_percent: float | None = Field(default=None, strict=True, ge=0, le=100)


def ingestion_run_summary_response(run: IngestionRunSummary) -> IngestionRunSummaryResponse:
    return IngestionRunSummaryResponse.model_validate(run.model_dump(mode="python"))


def ingestion_run_list_response(result: IngestionRunListResult) -> IngestionRunListResponse:
    return IngestionRunListResponse(
        items=tuple(ingestion_run_summary_response(item) for item in result.items),
        total=result.total,
    )


def ingestion_run_detail_response(result: IngestionRunDetailResult) -> IngestionRunDetailEnvelope:
    run: IngestionRunDetail = result.run
    return IngestionRunDetailEnvelope(run=IngestionRunDetailResponse.model_validate(run.model_dump(mode="python")))


__all__ = [
    "IngestionRunDetailEnvelope",
    "IngestionRunDetailResponse",
    "IngestionRunListResponse",
    "IngestionRunSummaryResponse",
    "IngestionRetryRequestBody",
    "SourceHealthItemResponse",
    "SourceHealthResponse",
    "DecisionAnalyticsFunnelResponse",
    "ingestion_run_detail_response",
    "ingestion_run_list_response",
]
