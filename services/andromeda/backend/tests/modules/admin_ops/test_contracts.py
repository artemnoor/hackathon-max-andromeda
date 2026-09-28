from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from andromeda.modules.admin_ops.contracts.public import IngestionRunFilters
from andromeda.modules.admin_ops.domain.entities import IngestionRunDetail, IngestionRunStatus, IngestionRunSummary


STARTED = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
FINISHED = datetime(2026, 9, 14, 10, 1, tzinfo=timezone.utc)


def _summary(**updates: object) -> IngestionRunSummary:
    values: dict[str, object] = {
        "id": "ingest:" + "a" * 32,
        "status": IngestionRunStatus.COMPLETED,
        "started_at": STARTED,
        "finished_at": FINISHED,
        "source_count": 2,
        "program_count": 2,
        "curriculum_item_count": 10,
        "event_count": 5,
        "campus_point_count": 5,
        "inserted_count": 3,
        "updated_count": 1,
        "unchanged_count": 4,
        "removed_count": 0,
    }
    values.update(updates)
    return IngestionRunSummary(**values)


def test_ingestion_run_contract_requires_consistent_lifecycle() -> None:
    assert _summary(status=IngestionRunStatus.RUNNING, finished_at=None).status is IngestionRunStatus.RUNNING
    with pytest.raises(ValidationError, match="terminal ingestion run"):
        _summary(finished_at=None)
    with pytest.raises(ValidationError, match="running ingestion run"):
        _summary(status=IngestionRunStatus.RUNNING)
    with pytest.raises(ValidationError, match="failed ingestion run"):
        _summary(status=IngestionRunStatus.FAILED)


def test_ingestion_run_filters_are_bounded_and_strict() -> None:
    assert IngestionRunFilters(limit=100).limit == 100
    with pytest.raises(ValidationError):
        IngestionRunFilters(limit=0)
    with pytest.raises(ValidationError):
        IngestionRunFilters(limit=101)


def test_ingestion_run_detail_validates_source_hashes() -> None:
    with pytest.raises(ValidationError):
        IngestionRunDetail(**_summary().model_dump(mode="python"), source_hashes=("invalid",), source_kinds=("fixture",))
