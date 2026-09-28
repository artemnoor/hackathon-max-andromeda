from __future__ import annotations

from pathlib import Path

from sqlalchemy import event as sqlalchemy_event

from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.infrastructure.repositories.university_catalog import SqlAlchemyUniversityCatalogCanonicalReader, SqlAlchemyUniversityCatalogRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.modules.university_admin.services.catalog import UniversityCatalogService


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def test_public_catalog_uses_bounded_batch_reads(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'catalog-query-count.db').as_posix()}")
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    sqlalchemy_event.listen(engine, "before_cursor_execute", capture)
    try:
        with session_scope(engine) as session:
            repository = SqlAlchemyUniversityCatalogRepository(session)
            catalog = UniversityCatalogService(
                repository,
                repository,
                SqlAlchemyUniversityCatalogCanonicalReader(session),
            ).public_catalog("university:bmstu")
    finally:
        sqlalchemy_event.remove(engine, "before_cursor_execute", capture)
        engine.dispose()

    assert catalog.programs
    assert catalog.disciplines
    assert len(statements) <= 12
