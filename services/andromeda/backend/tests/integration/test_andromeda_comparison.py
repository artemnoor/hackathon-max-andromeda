from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository


def test_full_backend_vertical_slice_compares_all_and_selected_semester(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'fullstack.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    client = TestClient(create_app(database_url))
    query = "program:09.03.01-02,program:09.03.01-12"
    all_response = client.get("/compare", params={"programIds": query})
    semester_response = client.get("/compare", params={"programIds": query, "scope": "semester", "semester": 1})
    assert all_response.status_code == semester_response.status_code == 200
    assert len(all_response.json()["rows"]) > len(semester_response.json()["rows"])
    assert all("hoursDelta" in row and "creditsDelta" in row for row in all_response.json()["rows"])
    assert "blocks" not in all_response.json()
    assert all("subjectGroup" not in row for row in all_response.json()["rows"])
