from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from andromeda.api.dependencies import get_ingestion_run_service, require_ops_access
from andromeda.api.schemas.admin_ops import IngestionRetryRequestBody, IngestionRunDetailEnvelope, IngestionRunListResponse, SourceHealthItemResponse, SourceHealthResponse, ingestion_run_detail_response, ingestion_run_list_response
from andromeda.modules.admin_ops.contracts.public import IngestionRetryRequest, IngestionRetrySource, IngestionRunFilters, IngestionRunStatus
from andromeda.modules.admin_ops.domain.entities import IngestionRunSummary
from andromeda.modules.admin_ops.contracts.results import IngestionRunDetailResult
from andromeda.modules.admin_ops.services.ingestion_runs import IngestionRunService
from andromeda.shared.contracts.ids import IngestRunId
from datetime import datetime, timezone
from typing import Literal, cast


logger = logging.getLogger("andromeda.api.admin_ops")
router = APIRouter(prefix="/ops/ingestion", tags=["admin-ops"])


@router.post("/runs/retry", response_model=IngestionRunDetailEnvelope, operation_id="retry_ingestion_run", dependencies=[Depends(require_ops_access)])
def retry_ingestion_run(
    body: IngestionRetryRequestBody,
    service: IngestionRunService = Depends(get_ingestion_run_service),
) -> IngestionRunDetailEnvelope:
    result = service.retry(
        IngestionRetryRequest(
            source=IngestionRetrySource(body.source),
            idempotency_key=body.idempotency_key,
            retry_of_run_id=body.retry_of_run_id,
        )
    )
    response = ingestion_run_detail_response(IngestionRunDetailResult(run=result.run))
    logger.info("admin_ops_ingestion_retry_complete run_id=%s source_profile=%s", result.run.id, result.run.source_profile)
    return response


@router.get("/runs", response_model=IngestionRunListResponse, operation_id="list_ingestion_runs", dependencies=[Depends(require_ops_access)])
def list_ingestion_runs(
    status: IngestionRunStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    service: IngestionRunService = Depends(get_ingestion_run_service),
) -> IngestionRunListResponse:
    result = service.list(IngestionRunFilters(status=status, limit=limit))
    response = ingestion_run_list_response(result)
    logger.info("admin_ops_ingestion_runs_complete result_count=%d total=%d", len(response.items), response.total)
    return response


@router.get("/runs/{id}", response_model=IngestionRunDetailEnvelope, operation_id="get_ingestion_run", dependencies=[Depends(require_ops_access)])
def get_ingestion_run(
    id: IngestRunId,
    service: IngestionRunService = Depends(get_ingestion_run_service),
) -> IngestionRunDetailEnvelope:
    result = service.get(id)
    response = ingestion_run_detail_response(result)
    logger.info("admin_ops_ingestion_run_detail_complete run_id=%s", id)
    return response


@router.get("/source-health", response_model=SourceHealthResponse, operation_id="get_source_health", dependencies=[Depends(require_ops_access)])
def get_source_health(
    service: IngestionRunService = Depends(get_ingestion_run_service),
) -> SourceHealthResponse:
    runs = service.list(IngestionRunFilters(limit=100)).items
    by_university: dict[str, list[IngestionRunSummary]] = {}
    for run in runs:
        if run.university_id:
            by_university.setdefault(run.university_id, []).append(run)
    items: list[SourceHealthItemResponse] = []
    now = datetime.now(timezone.utc)
    for university_id, candidates in sorted(by_university.items()):
        latest = candidates[0]
        successful = next((run for run in candidates if run.status is IngestionRunStatus.COMPLETED), None)
        age_seconds = int(max(0, (now - successful.finished_at).total_seconds())) if successful and successful.finished_at else None
        state: Literal["fresh", "stale", "degraded", "failed"]
        if latest.status is IngestionRunStatus.RUNNING:
            state = "degraded"
        elif latest.status is IngestionRunStatus.FAILED and successful is None:
            state = "failed"
        elif latest.status is IngestionRunStatus.FAILED or (
            successful
            and (successful.critical_gap_count > 0 or successful.quality_status in {"degraded", "rejected"})
        ):
            state = "degraded"
        elif age_seconds is None or age_seconds > 30 * 24 * 60 * 60:
            state = "stale"
        else:
            state = "fresh" if age_seconds <= 7 * 24 * 60 * 60 else "stale"
        items.append(SourceHealthItemResponse(
            university_id=university_id,
            state=state,
            latest_successful_run_id=successful.id if successful else None,
            latest_attempt_run_id=latest.id,
            age_seconds=age_seconds,
            source_gap_count=successful.source_gap_count if successful else latest.source_gap_count,
            critical_gap_count=successful.critical_gap_count if successful else latest.critical_gap_count,
            drift_status=cast(Literal["not_checked", "passed", "rejected"], latest.drift_status),
        ))
    return SourceHealthResponse(items=tuple(items))


__all__ = ["router"]
