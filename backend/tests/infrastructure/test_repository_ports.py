from __future__ import annotations

from pathlib import Path

from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.database import models as _models
from andromeda.infrastructure.repositories.curricula import SqlAlchemyCurriculumRepository
from andromeda.infrastructure.repositories.programs import SqlAlchemyProgramRepository


def test_repositories_return_public_contracts_not_orm_models(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'ports.db').as_posix()}")
    Base.metadata.create_all(engine)
    from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository

    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    with session_scope(engine) as session:
        program = SqlAlchemyProgramRepository(session).get(canonical.programs[0].id)
        curriculum = SqlAlchemyCurriculumRepository(session).get_for_program(canonical.programs[0].id)
    assert program is not None and program.__class__.__module__.startswith("andromeda.modules")
    assert curriculum is not None and curriculum.items
