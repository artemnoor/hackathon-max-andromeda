from __future__ import annotations

from collections.abc import Sequence

import pytest

from andromeda.modules.admin_ops.contracts.public import IngestionRunFilters
from andromeda.modules.admin_ops.contracts.results import IngestionRunDetailResult, IngestionRunListResult
from andromeda.modules.admin_ops.domain.entities import IngestionRunDetail, IngestionRunStatus, IngestionRunSummary
from andromeda.modules.admin_ops.services.ingestion_runs import IngestionRunService
from andromeda.shared.contracts.errors import NotFoundError

from .test_contracts import FINISHED, STARTED


def _run(identifier: str, *, status: IngestionRunStatus = IngestionRunStatus.COMPLETED) -> IngestionRunSummary:
    return IngestionRunSummary(
        id=identifier,
        status=status,
        started_at=STARTED,
        finished_at=FINISHED if status is not IngestionRunStatus.RUNNING else None,
        source_count=1,
        program_count=2,
        curriculum_item_count=3,
        event_count=4,
        campus_point_count=5,
        inserted_count=6,
        updated_count=0,
        unchanged_count=0,
        removed_count=0,
        error_code="INGESTION_FAILED" if status is IngestionRunStatus.FAILED else None,
    )


class FakeReader:
    def __init__(self, runs: Sequence[IngestionRunSummary]) -> None:
        self.runs = tuple(runs)
        self.last_filters: IngestionRunFilters | None = None

    def list(self, filters: IngestionRunFilters) -> IngestionRunListResult:
        self.last_filters = filters
        selected = tuple(run for run in self.runs if filters.status is None or run.status is filters.status)
        return IngestionRunListResult(items=selected[: filters.limit], total=len(selected))

    def get(self, run_id: str) -> IngestionRunDetailResult | None:
        for run in self.runs:
            if run.id == run_id:
                return IngestionRunDetailResult(run=IngestionRunDetail(**run.model_dump(mode="python"), source_hashes=(), source_kinds=()))
        return None


def test_service_forwards_bounded_filters_and_returns_typed_results() -> None:
    completed = _run("ingest:" + "a" * 32)
    failed = _run("ingest:" + "b" * 32, status=IngestionRunStatus.FAILED)
    reader = FakeReader((completed, failed))
    service = IngestionRunService(reader)

    result = service.list(IngestionRunFilters(status=IngestionRunStatus.FAILED, limit=1))

    assert result.total == 1
    assert result.items == (failed,)
    assert reader.last_filters is not None
    assert reader.last_filters.status is IngestionRunStatus.FAILED


def test_service_raises_typed_not_found() -> None:
    service = IngestionRunService(FakeReader(()))

    with pytest.raises(NotFoundError, match="not found"):
        service.get("ingest:" + "c" * 32)  # type: ignore[arg-type]
