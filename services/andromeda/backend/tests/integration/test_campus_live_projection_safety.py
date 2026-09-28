from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import VenueModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
CAMPUS_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "campus" / "raw"


def test_missing_live_campus_source_does_not_delete_existing_projection(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=TRACER_FIXTURE_DIR, campus_fixture_dir=CAMPUS_FIXTURE_DIR)
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'campus-safety.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.ingest(raw, canonical)

    without_campus = raw.model_copy(
        update={
            "snapshots": tuple(snapshot for snapshot in raw.snapshots if snapshot.source_kind != "bmstu_campus_points"),
            "campus_points": (),
        }
    )
    repository.ingest(without_campus, canonical.model_copy(update={"campus_points": ()}))

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(VenueModel)) == 5
        main = session.get(VenueModel, "venue:bmstu:main-campus")
        assert main is not None and main.point_type == "building"
