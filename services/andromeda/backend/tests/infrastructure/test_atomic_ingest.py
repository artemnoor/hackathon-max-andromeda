from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import CurriculumItemModel, IngestRunModel, ProgramModel, RawSourceRecordModel, SourceSnapshotModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.infrastructure.repositories.ingestion_recovery import SqlAlchemyIngestionRunRecovery


def test_ingest_is_atomic_on_identity_conflict(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'atomic.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.ingest(raw, canonical)
    conflict = canonical.model_copy(
        update={"programs": (canonical.programs[0].model_copy(update={"code": "09.03.01-99"}), *canonical.programs[1:])}
    )
    try:
        repository.ingest(raw, conflict)
    except Exception:
        pass
    else:
        raise AssertionError("identity conflict must fail")
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IngestRunModel)) == 2
        failed_run = session.scalar(select(IngestRunModel).where(IngestRunModel.status == "failed"))
        assert failed_run is not None
        assert failed_run.error_code == "SOURCE_CONTRACT_ERROR"
        assert failed_run.error_message == "Ingestion failed"
        assert session.scalar(select(func.count()).select_from(ProgramModel)) == 2


def test_ingest_updates_mutable_projection_and_removes_stale_items(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'refresh.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.ingest(raw, canonical)

    original_curriculum = canonical.curricula[0]
    shortened_curriculum = original_curriculum.model_copy(update={"items": original_curriculum.items[:-1]})
    updated = canonical.model_copy(
        update={
            "programs": (canonical.programs[0].model_copy(update={"name": "Обновлённая программа"}), *canonical.programs[1:]),
            "curricula": (shortened_curriculum, *canonical.curricula[1:]),
        }
    )
    repository.ingest(raw, updated)

    with Session(engine) as session:
        assert session.get(ProgramModel, canonical.programs[0].id).name == "Обновлённая программа"
        item_count = session.scalar(
            select(func.count()).select_from(CurriculumItemModel).where(CurriculumItemModel.curriculum_id == original_curriculum.id)
        )
        assert item_count == len(shortened_curriculum.items)


def test_ingest_is_idempotent_for_same_canonical_snapshot(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'idempotent.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)

    repository.ingest(raw, canonical)
    repository.ingest(raw, canonical)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IngestRunModel)) == 2
        assert session.scalar(select(func.count()).select_from(IngestRunModel).where(IngestRunModel.status == "completed")) == 2
        assert session.scalar(select(func.count()).select_from(ProgramModel)) == 2
        assert session.scalar(select(func.count()).select_from(SourceSnapshotModel)) == len(raw.snapshots)
        assert session.scalar(select(func.count()).select_from(RawSourceRecordModel)) > 0


def test_projection_failure_marks_run_failed_and_preserves_last_good_snapshot(tmp_path: Path, monkeypatch) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'projection-failure.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.ingest(raw, canonical)

    original_name = canonical.programs[0].name
    updated = canonical.model_copy(
        update={"programs": (canonical.programs[0].model_copy(update={"name": "must rollback"}), *canonical.programs[1:])}
    )

    def fail_projection(*args, **kwargs):
        raise RuntimeError("injected projection failure")

    monkeypatch.setattr(SqlAlchemyIngestionRepository, "_insert_domain", fail_projection)
    with pytest.raises(RuntimeError, match="injected projection failure"):
        repository.ingest(raw, updated)

    with Session(engine) as session:
        program = session.get(ProgramModel, canonical.programs[0].id)
        assert program is not None
        assert program.name == original_name
        failed = session.scalar(select(IngestRunModel).where(IngestRunModel.status == "failed"))
        assert failed is not None
        assert failed.projection_status == "failed"
        assert failed.error_message == "Ingestion failed"


def test_terminal_update_failure_leaves_recoverable_committed_state(tmp_path: Path, monkeypatch) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'terminal-failure.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)

    def fail_terminal(self, run_id, stats):
        raise RuntimeError("injected terminal update failure")

    monkeypatch.setattr(SqlAlchemyIngestionRepository, "_mark_completed", fail_terminal)
    with pytest.raises(RuntimeError, match="injected terminal update failure"):
        repository.ingest(raw, canonical)

    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as session:
        row = session.scalar(select(IngestRunModel).where(IngestRunModel.status == "running"))
        assert row is not None
        run_id = row.id
        assert row.projection_status == "committed"
        row.heartbeat_at = now - timedelta(hours=2)
        session.commit()

    assert SqlAlchemyIngestionRunRecovery(engine).recover_stale(timeout_seconds=60, now=now) == (run_id,)
    with Session(engine) as session:
        recovered = session.get(IngestRunModel, run_id)
        assert recovered is not None
        assert recovered.status == "failed"
        assert recovered.error_code == "INGESTION_COMPLETION_UNCONFIRMED"
        assert recovered.recovery_reason == "projection_committed_terminal_update_missing"
