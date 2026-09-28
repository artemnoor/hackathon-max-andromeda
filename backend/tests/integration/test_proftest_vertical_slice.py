from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_fixture_db_to_proftest_api_vertical_slice(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'vertical-proftest.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    client = TestClient(create_app(database_url))
    request = {
        "answers": [
            {"questionId": "interest_free_day", "optionIds": ["data_story"]},
            {"questionId": "interest_investigation", "optionIds": ["prove_model"]},
            {"questionId": "activity_build", "optionIds": ["tested_hypothesis"]},
            {"questionId": "activity_working_style", "optionIds": ["analyze_options"]},
            {"questionId": "anti_subjects", "optionIds": ["avoid_physics"], "intensity": 1.0},
            {"questionId": "activity_depth", "optionIds": ["deep_theory"]},
        ]
    }

    response = client.post("/proftest/results", json=request)

    assert response.status_code == 200
    assert response.json()["profile"]["confidence"]["answeredBase"] == 6
    assert len(response.json()["recommendations"]) == 2
