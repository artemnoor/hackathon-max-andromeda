from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import EventModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_missing_event_source_does_not_delete_existing_projection(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'event-safety.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.ingest(raw, canonical)
    without_events = raw.model_copy(update={"snapshots": tuple(snapshot for snapshot in raw.snapshots if snapshot.source_kind != "bmstu_events"), "events": ()})
    repository.ingest(without_events, canonical.model_copy(update={"events": ()}))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(EventModel)) == 5
