from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import ProgramModel, IngestRunModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_replay_is_idempotent_for_domain_rows(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
    adapter = BmstuUniversityAdapter()
    try:
        raw, normalized = adapter.parse_sources(mode="fixture", fixture_dir=fixture_dir)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'replay.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    service = SqlAlchemyIngestionRepository(engine)
    service.ingest(raw, normalized)
    service.ingest(raw, normalized)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IngestRunModel)) == 2
        assert session.scalar(select(func.count()).select_from(ProgramModel)) == 2
    engine.dispose()


def test_partial_ingest_rolls_back_when_identity_conflicts(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
    adapter = BmstuUniversityAdapter()
    try:
        raw, normalized = adapter.parse_sources(mode="fixture", fixture_dir=fixture_dir)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'rollback.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    service = SqlAlchemyIngestionRepository(engine)
    service.ingest(raw, normalized)
    conflicting_program = normalized.programs[0].model_copy(update={"code": "09.03.01-99"})
    conflicting = normalized.model_copy(update={"programs": (conflicting_program, *normalized.programs[1:])})

    try:
        service.ingest(raw, conflicting)
    except Exception:
        pass
    else:
        raise AssertionError("conflicting identity must fail")

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IngestRunModel)) == 2
        failed_run = session.scalar(select(IngestRunModel).where(IngestRunModel.status == "failed"))
        assert failed_run is not None
        assert failed_run.error_code == "SOURCE_CONTRACT_ERROR"
        assert failed_run.error_message == "Ingestion failed"
        assert session.scalar(select(func.count()).select_from(ProgramModel)) == 2
    engine.dispose()
