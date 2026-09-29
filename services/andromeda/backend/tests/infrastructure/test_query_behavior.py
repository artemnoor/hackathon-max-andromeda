from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session

from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.curricula import SqlAlchemyCurriculumRepository
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository


def test_curriculum_read_loads_assessments_with_one_bounded_query(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'query-behavior.db').as_posix()}")
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as session:
            curriculum = SqlAlchemyCurriculumRepository(session).get_for_program(canonical.programs[0].id)
            assert curriculum is not None
            assert curriculum.items
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        engine.dispose()

    assessment_queries = [statement for statement in statements if "curriculum_item_assessments" in statement]
    assert len(assessment_queries) == 1
