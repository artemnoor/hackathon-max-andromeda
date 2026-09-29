from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.modules.admin_ops.contracts.public import IngestionRunFilters
from andromeda.modules.admin_ops.contracts.results import IngestionRunDetailResult, IngestionRunListResult
from andromeda.modules.admin_ops.domain.entities import IngestionRunDetail, IngestionRunStatus, IngestionRunSummary
from andromeda.modules.admin_ops.repository.ports import IngestionRunReader
from andromeda.shared.contracts.errors import ContractError, ErrorCode
from andromeda.shared.contracts.ids import IngestRunId, SourceHash

from ..database.models import IngestRunModel


logger = logging.getLogger("andromeda.infrastructure.repositories.admin_ops")
_SOURCE_HASHES = TypeAdapter(tuple[SourceHash, ...])


class SqlAlchemyIngestionRunReader(IngestionRunReader):
    """Read bounded ingestion audit data without selecting raw provenance bodies."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self, filters: IngestionRunFilters) -> IngestionRunListResult:
        query = select(IngestRunModel)
        if filters.status is not None:
            query = query.where(IngestRunModel.status == filters.status.value)
        total = int(self._session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rows = self._session.execute(
            query.order_by(IngestRunModel.started_at.desc(), IngestRunModel.id.desc()).limit(filters.limit)
        ).scalars().all()
        items = tuple(_to_summary(row) for row in rows)
        logger.info("ingestion_run_read_complete result_count=%d total=%d", len(items), total)
        return IngestionRunListResult(items=items, total=total)

    def get(self, run_id: IngestRunId) -> IngestionRunDetailResult | None:
        row = self._session.get(IngestRunModel, run_id)
        if row is None:
            return None
        return IngestionRunDetailResult(run=_to_detail(row))


def _to_summary(row: IngestRunModel) -> IngestionRunSummary:
    return IngestionRunSummary(**_base_values(row))


def _to_detail(row: IngestRunModel) -> IngestionRunDetail:
    try:
        hashes = _SOURCE_HASHES.validate_python(_json_list(row.source_hashes_json, row.id, "source_hashes"))
        kinds = tuple(_json_list(row.source_kinds_json, row.id, "source_kinds"))
        values: dict[str, Any] = _base_values(row)
        values["source_hashes"] = hashes
        values["source_kinds"] = kinds
        return IngestionRunDetail(**values)
    except (ValidationError, ValueError) as exc:
        logger.error("ingestion_run_contract_invalid run_id=%s", row.id)
        raise ContractError(ErrorCode.CONTRACT_ERROR, "Ingestion audit data is invalid") from exc


def _base_values(row: IngestRunModel) -> dict[str, Any]:
    try:
        status = IngestionRunStatus(row.status)
        return {
            "id": row.id,
            "status": status,
            "started_at": _aware(row.started_at),
            "finished_at": _aware(row.finished_at) if row.finished_at is not None else None,
            "source_count": row.source_count,
            "program_count": row.program_count,
            "curriculum_item_count": row.curriculum_item_count,
            "event_count": row.event_count,
            "campus_point_count": row.campus_point_count,
            "inserted_count": row.inserted_count,
            "updated_count": row.updated_count,
            "unchanged_count": row.unchanged_count,
            "removed_count": row.removed_count,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "university_id": row.university_id,
            "duration_ms": row.duration_ms,
            "source_gap_count": row.source_gap_count,
            "critical_gap_count": row.critical_gap_count,
            "drift_status": row.drift_status,
            "quality_status": row.quality_status,
            "previous_good_run_id": row.previous_good_run_id,
            "source_profile": row.source_profile,
            "source_revision": row.source_revision,
            "configuration_version": row.configuration_version,
            "retry_of_run_id": row.retry_of_run_id,
            "projection_target": row.projection_target,
            "heartbeat_at": _aware(row.heartbeat_at),
            "projection_status": row.projection_status,
            "recovery_reason": row.recovery_reason,
        }
    except (ValidationError, ValueError) as exc:
        logger.error("ingestion_run_contract_invalid run_id=%s", row.id)
        raise ContractError(ErrorCode.CONTRACT_ERROR, "Ingestion audit data is invalid") from exc


def _json_list(value: str, run_id: str, field_name: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.error("ingestion_run_json_invalid run_id=%s field=%s", run_id, field_name)
        raise ValueError("invalid ingestion audit JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) and item for item in parsed):
        logger.error("ingestion_run_json_invalid run_id=%s field=%s", run_id, field_name)
        raise ValueError("invalid ingestion audit JSON")
    return parsed


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None and value.utcoffset() is not None else value.replace(tzinfo=timezone.utc)


__all__ = ["SqlAlchemyIngestionRunReader"]
