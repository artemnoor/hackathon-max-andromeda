from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from ..database.models import IngestRunModel
from ..database.session import session_factory


logger = logging.getLogger("andromeda.infrastructure.repositories.ingestion_recovery")


class SqlAlchemyIngestionRunRecovery:
    """Recover only runs that exceeded the explicit operational timeout."""

    def __init__(self, engine: Any) -> None:
        self._factory = session_factory(engine)

    def recover_stale(self, *, timeout_seconds: int, now: datetime | None = None) -> tuple[str, ...]:
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        finished_at = now or datetime.now(timezone.utc)
        cutoff = finished_at - timedelta(seconds=timeout_seconds)
        recovered: list[str] = []
        with self._factory() as session:
            with session.begin():
                rows = session.scalars(
                    select(IngestRunModel)
                    .where(
                        IngestRunModel.status == "running",
                        func.coalesce(IngestRunModel.heartbeat_at, IngestRunModel.started_at) < cutoff,
                    )
                    .with_for_update()
                ).all()
                for row in rows:
                    projection_was_committed = row.projection_status == "committed"
                    row.status = "failed"
                    row.finished_at = finished_at
                    row.duration_ms = _duration_ms(row.started_at, finished_at)
                    row.heartbeat_at = finished_at
                    row.error_code = (
                        "INGESTION_COMPLETION_UNCONFIRMED" if projection_was_committed else "INGESTION_STALE_TIMEOUT"
                    )
                    row.error_message = (
                        "Canonical projection committed, but the terminal run update was not confirmed"
                        if projection_was_committed
                        else "Ingestion run exceeded the operational timeout"
                    )
                    row.recovery_reason = (
                        "projection_committed_terminal_update_missing"
                        if projection_was_committed
                        else "lease_expired_before_terminal_update"
                    )
                    if not projection_was_committed:
                        row.projection_status = "failed"
                    logger.warning(
                        "ingest_run_recovered run_id=%s prior_status=running projection=%s error_code=%s reason=%s",
                        row.id,
                        row.projection_status,
                        row.error_code,
                        row.recovery_reason,
                    )
                    recovered.append(row.id)
        return tuple(recovered)


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    started = started_at if started_at.tzinfo is not None else started_at.replace(tzinfo=timezone.utc)
    finished = finished_at if finished_at.tzinfo is not None else finished_at.replace(tzinfo=timezone.utc)
    return max(0, int((finished - started).total_seconds() * 1000))


__all__ = ["SqlAlchemyIngestionRunRecovery"]
