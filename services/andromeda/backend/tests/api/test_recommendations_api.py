from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def _client(tmp_path: Path) -> TestClient:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'recommendations-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    return TestClient(create_app(database_url))


def _answers() -> dict[str, object]:
    return {
        "answers": [
            {"questionId": "interest_free_day", "optionIds": ["software_tool"]},
            {"questionId": "interest_investigation", "optionIds": ["prove_model"]},
            {"questionId": "activity_build", "optionIds": ["system_scheme"]},
            {"questionId": "activity_working_style", "optionIds": ["analyze_options"]},
            {"questionId": "anti_subjects", "optionIds": ["avoid_physics"], "intensity": 0.9},
            {"questionId": "activity_depth", "optionIds": ["practical_prototype"]},
        ]
    }


def test_recommendations_accept_profile_contract_and_return_real_evidence(tmp_path: Path) -> None:
    client = _client(tmp_path)
    profile = client.post("/proftest/results", json=_answers()).json()["profile"]
    response = client.post("/recommendations", json={"profile": profile, "limit": 2})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["recommendations"]) == 2
    assert all(0 <= item["contentFit"] <= 100 for item in payload["recommendations"])
    assert Decimal(payload["recommendations"][0]["score"]["breakdown"]["antiPenalty"]) >= 0
    assert payload["recommendations"][0]["provenance"]
    assert payload["recommendations"][0]["reasons"][0]["provenance"]
    evidence = payload["recommendations"][0]["evidence"]
    assert evidence["policyVersion"] == "content-fit.v1"
    assert evidence["taxonomyVersion"] == "taxonomy-22.v1"
    assert evidence["reliability"]["status"] in {"available", "partial", "not_available"}
    assert "curriculum_activity_mapping" in evidence["inferredSignals"]
    assert "workloadReadiness" not in payload["recommendations"][0]
    assert "careerFit" not in payload["recommendations"][0]


def test_recommendations_reject_unknown_fields_and_invalid_limit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    profile = client.post("/proftest/results", json=_answers()).json()["profile"]

    extra = client.post("/recommendations", json={"profile": profile, "limit": 2, "unexpected": True})
    invalid = client.post("/recommendations", json={"profile": profile, "limit": 0})

    assert extra.status_code == 422
    assert invalid.status_code == 422
    assert extra.json()["code"] == "VALIDATION_ERROR"
