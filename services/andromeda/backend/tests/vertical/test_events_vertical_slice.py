from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_events_fixture_crosses_contract_projection_service_and_api(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    assert raw.events and canonical.events
    database_url = f"sqlite:///{(tmp_path / 'events-vertical.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.ingest(raw, canonical)
    repository.ingest(raw, canonical)

    response = TestClient(create_app(database_url)).get("/events")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 5
    assert payload["items"][0]["provenance"][0]["kind"] == "bmstu_events"
    assert payload["items"][0]["universityIds"] == ["university:bmstu"]
