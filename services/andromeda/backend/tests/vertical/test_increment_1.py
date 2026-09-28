from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_first_real_program_crosses_parser_db_and_api(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, normalized = adapter.parse_sources(
            mode="fixture",
            fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw",
            program_codes=("09.03.01-02",),
        )
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'increment-1.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, normalized)

    response = TestClient(create_app(database_url)).get("/programs/program:09.03.01-02")

    assert response.status_code == 200
    payload = response.json()
    assert payload["program"]["id"] == "program:bmstu:09.03.01-02"
    assert payload["program"]["directionId"] == "direction:bmstu:09.03.01"
    engine.dispose()
