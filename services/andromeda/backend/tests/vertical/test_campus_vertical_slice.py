from __future__ import annotations

from pathlib import Path

from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.repositories.campus import SqlAlchemyCampusPointRepository
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.modules.campus.contracts.public import CampusPointFilters
from andromeda.modules.campus.services.campus import CampusService


TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
CAMPUS_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "campus" / "raw"


def test_campus_fixture_crosses_contract_projection_and_application_service(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=TRACER_FIXTURE_DIR, campus_fixture_dir=CAMPUS_FIXTURE_DIR)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'campus-vertical.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    with session_scope(engine) as session:
        result = CampusService(SqlAlchemyCampusPointRepository(session)).list(CampusPointFilters())
    assert result.total == len(canonical.campus_points) == 5
    assert result.items[0].id == "venue:bmstu:assembly-hall"
