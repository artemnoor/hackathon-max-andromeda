from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import IngestRunModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.infrastructure.repositories.ingestion_recovery import SqlAlchemyIngestionRunRecovery
from andromeda.shared.contracts.errors import ConflictError


def test_stale_running_run_is_recovered_with_operator_visible_error(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'stale.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    run_id = repository.start_run(source_profile="bmstu:fixture:test", source_revision="fixture-v1", configuration_version="test.v1")
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        row = session.get(IngestRunModel, run_id)
        assert row is not None
        row.started_at = now - timedelta(hours=2)
        row.heartbeat_at = now - timedelta(hours=2)
        session.commit()

    recovered = SqlAlchemyIngestionRunRecovery(engine).recover_stale(timeout_seconds=60, now=now)

    assert recovered == (run_id,)
    with Session(engine) as session:
        row = session.scalar(select(IngestRunModel).where(IngestRunModel.id == run_id))
        assert row is not None
        assert row.status == "failed"
        assert row.error_code == "INGESTION_STALE_TIMEOUT"
        assert row.finished_at is not None
        assert row.finished_at.replace(tzinfo=timezone.utc) == now


def test_second_running_run_is_rejected_with_existing_run_id(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'single-running.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    run_id = repository.start_run()

    with pytest.raises(ConflictError) as error:
        repository.start_run()

    assert error.value.details[0].path == "run_id"
    assert error.value.details[0].message == run_id


def test_active_run_identity_is_scoped_by_university_and_profile(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'scoped-running.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)

    bmstu_run = repository.start_run(
        university_id="university:bmstu",
        source_profile="fixture:v1",
        projection_target="canonical",
    )
    hse_run = repository.start_run(
        university_id="university:hse",
        source_profile="fixture:v1",
        projection_target="canonical",
    )
    assert hse_run != bmstu_run

    with pytest.raises(ConflictError) as error:
        repository.start_run(
            university_id="university:bmstu",
            source_profile="fixture:v1",
            projection_target="canonical",
        )

    assert error.value.details[0].message == bmstu_run


def test_idempotency_key_returns_existing_run_without_creating_a_second_row(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'idempotency.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)

    first = repository.start_run(
        university_id="university:bmstu",
        source_profile="fixture:v1",
        idempotency_key="retry-key-001",
    )
    second = repository.start_run(
        university_id="university:bmstu",
        source_profile="fixture:v1",
        idempotency_key="retry-key-001",
    )

    assert second == first
    with Session(engine) as session:
        assert session.scalar(select(IngestRunModel.id).where(IngestRunModel.id == first)) == first
        assert session.scalar(select(IngestRunModel.id).where(IngestRunModel.id != first)) is None


def test_committed_projection_without_terminal_update_is_recovered_as_unconfirmed(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'committed-recovery.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    run_id = repository.start_run(university_id="university:bmstu", source_profile="fixture:v1")
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        row = session.get(IngestRunModel, run_id)
        assert row is not None
        row.heartbeat_at = now - timedelta(hours=2)
        row.projection_status = "committed"
        session.commit()

    assert SqlAlchemyIngestionRunRecovery(engine).recover_stale(timeout_seconds=60, now=now) == (run_id,)
    with Session(engine) as session:
        row = session.get(IngestRunModel, run_id)
        assert row is not None
        assert row.status == "failed"
        assert row.error_code == "INGESTION_COMPLETION_UNCONFIRMED"
        assert row.projection_status == "committed"
        assert row.recovery_reason == "projection_committed_terminal_update_missing"
