from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
CAMPUS_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "campus" / "raw"


def _client(tmp_path: Path) -> TestClient:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=TRACER_FIXTURE_DIR, campus_fixture_dir=CAMPUS_FIXTURE_DIR)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'campus-api.db').as_posix()}"
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


def test_campus_points_list_detail_and_point_events_are_read_contracts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    listed = client.get("/campus/points", params={"pointType": "building", "programId": "program:09.03.01-02"})
    detail = client.get("/campus/points/venue:bmstu:main-campus")
    events = client.get("/campus/points/venue:bmstu:main-campus/events")
    missing = client.get("/campus/points/venue:bmstu:missing")
    invalid = client.get(
        "/campus/points/venue:bmstu:main-campus/events",
        params={"from": "2026-12-01T00:00:00+00:00", "to": "2026-01-01T00:00:00+00:00"},
    )

    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == "venue:bmstu:main-campus"
    assert detail.status_code == 200, detail.text
    assert detail.json()["pointType"] == "building"
    assert detail.json()["universityIds"] == ["university:bmstu"]
    assert detail.json()["programs"][0]["id"] == "program:bmstu:09.03.01-02"
    assert events.status_code == 200, events.text
    assert events.json()["pointId"] == "venue:bmstu:main-campus"
    assert events.json()["items"][0]["id"] == "event:bmstu:dod-2026"
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    assert invalid.status_code == 422 and invalid.json()["code"] == "VALIDATION_ERROR"


def test_campus_recommendations_require_profile_and_split_unplaced_events(tmp_path: Path) -> None:
    client = _client(tmp_path)
    missing_profile = client.get("/campus/recommendations")
    profile = client.post("/proftest/results", json=_answers())
    recommendations = client.get("/campus/recommendations")
    recommended_events = client.get(
        "/campus/points/venue:bmstu:main-campus/events",
        params={"recommended": "true"},
    )

    assert missing_profile.status_code == 404 and missing_profile.json()["code"] == "NOT_FOUND"
    assert profile.status_code == 200, profile.text
    assert recommendations.status_code == 200, recommendations.text
    payload = recommendations.json()
    assert payload["recommendations"]
    assert payload["recommendedProgramIds"]
    assert payload["points"]
    assert payload["events"]
    assert {item["id"] for item in payload["eventsWithoutPoint"]} >= {
        "event:bmstu:online-open-lecture-2026",
        "event:bmstu:career-hybrid-2026",
    }
    assert recommended_events.status_code == 200, recommended_events.text
    assert all(item["programIds"] for item in recommended_events.json()["items"])
