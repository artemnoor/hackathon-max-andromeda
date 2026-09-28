from __future__ import annotations

from pathlib import Path

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.curricula import SqlAlchemyCurriculumRepository
from andromeda.infrastructure.repositories.disciplines import SqlAlchemyDisciplineRepository
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.infrastructure.repositories.programs import SqlAlchemyProgramRepository
from andromeda.infrastructure.repositories.proftest import SqlAlchemyProftestCatalogRepository
from andromeda.modules.proftest.services.catalog import ProftestCatalogService
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_db_readers_feed_proftest_without_orm_leak(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'proftest.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    with engine.begin() as connection:
        from sqlalchemy.orm import Session

        reader = SqlAlchemyProftestCatalogRepository(
            SqlAlchemyProgramRepository(Session(bind=connection)),
            SqlAlchemyCurriculumRepository(Session(bind=connection)),
            SqlAlchemyDisciplineRepository(Session(bind=connection)),
        )
        fingerprints = ProftestCatalogService(reader).list_fingerprints()

    assert len(fingerprints) == 2
    assert all(fingerprint.total_hours > 0 for fingerprint in fingerprints)
    assert all(fingerprint.evidence for fingerprint in fingerprints)
