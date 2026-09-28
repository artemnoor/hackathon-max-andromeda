from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import IngestRunModel
from andromeda.infrastructure.repositories.admin_ops import SqlAlchemyIngestionRunReader
from andromeda.modules.admin_ops.contracts.public import IngestionRunFilters
from andromeda.modules.admin_ops.domain.entities import IngestionRunStatus
from andromeda.shared.contracts.errors import ContractError


def _run(identifier: str, started_at: datetime, *, status: str = "completed") -> IngestRunModel:
    return IngestRunModel(
        id=identifier,
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=1),
        status=status,
        error_code="INGESTION_FAILED" if status == "failed" else None,
        error_message="Ingestion failed" if status == "failed" else None,
        source_count=1,
        program_count=2,
        curriculum_item_count=3,
        event_count=4,
        campus_point_count=5,
        inserted_count=6,
        updated_count=7,
        unchanged_count=8,
        removed_count=9,
        source_hashes_json='["' + "a" * 64 + '"]',
        source_kinds_json='["bmstu_fixture"]',
    )


def test_reader_lists_bounded_audit_views_and_reads_validated_detail(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'admin-ops.db').as_posix()}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add_all((_run("ingest:" + "a" * 32, now), _run("ingest:" + "b" * 32, now + timedelta(minutes=1), status="failed")))
        session.commit()

    reader = SqlAlchemyIngestionRunReader(Session(engine))
    result = reader.list(IngestionRunFilters(limit=1))
    assert result.total == 2
    assert len(result.items) == 1
    assert result.items[0].id == "ingest:" + "b" * 32

    failed = reader.list(IngestionRunFilters(status=IngestionRunStatus.FAILED))
    assert failed.total == 1
    detail = reader.get("ingest:" + "b" * 32)
    assert detail is not None
    assert detail.run.source_hashes == ("a" * 64,)
    assert detail.run.source_kinds == ("bmstu_fixture",)


def test_reader_rejects_malformed_source_metadata(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'admin-ops-invalid.db').as_posix()}")
    Base.metadata.create_all(engine)
    row = _run("ingest:" + "c" * 32, datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc))
    row.source_hashes_json = '["not-a-sha256"]'
    with Session(engine) as session:
        session.add(row)
        session.commit()

    reader = SqlAlchemyIngestionRunReader(Session(engine))
    with pytest.raises(ContractError, match="invalid"):
        reader.get("ingest:" + "c" * 32)
