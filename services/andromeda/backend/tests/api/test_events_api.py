from __future__ import annotations

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
    database_url = f"sqlite:///{(tmp_path / 'events-api.db').as_posix()}"
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


def test_events_list_detail_and_filters_are_public_contracts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/events", params={"kind": "additional_education", "programId": "program:09.03.01-02"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    assert {item["id"] for item in payload["items"]} == {"event:bmstu:dod-2026", "event:bmstu:robotics-workshop-2026"}
    assert payload["items"][0]["startsAt"].endswith("+03:00") or payload["items"][0]["startsAt"].endswith("Z")
    assert payload["items"][0]["registrationUrl"].startswith("https://")
    assert payload["items"][0]["venue"]["address"]
    assert payload["items"][0]["venue"]["latitude"] is not None

    detail = client.get("/events/event:bmstu:dod-2026")
    missing = client.get("/events/event:bmstu:missing")
    invalid = client.get("/events", params={"to": "2026-01-01T00:00:00+00:00", "from": "2026-02-01T00:00:00+00:00"})
    assert detail.status_code == 200 and detail.json()["event"]["id"] == "event:bmstu:dod-2026"
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    assert invalid.status_code == 422 and invalid.json()["code"] == "VALIDATION_ERROR"


def test_recommended_events_require_profile_and_use_program_intersection(tmp_path: Path) -> None:
    client = _client(tmp_path)
    missing_profile = client.get("/events", params={"recommended": "true"})
    assert missing_profile.status_code == 404

    profile = client.post("/proftest/results", json=_answers())
    assert profile.status_code == 200, profile.text
    recommendations = {item["programId"] for item in profile.json()["recommendations"]}
    recommended = client.get("/events", params={"recommended": "true"})
    assert recommended.status_code == 200, recommended.text
    result_ids = {item["id"] for item in recommended.json()["items"]}
    assert "event:bmstu:research-day-2026" not in result_ids
    assert all(set(item["programIds"]) & recommendations for item in recommended.json()["items"])
