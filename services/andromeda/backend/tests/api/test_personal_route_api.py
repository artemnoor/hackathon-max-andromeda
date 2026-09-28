from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
EVENT_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "events" / "raw"
CAMPUS_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "campus" / "raw"


def _client(tmp_path: Path) -> TestClient:
    tmp_path.mkdir(parents=True, exist_ok=True)
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(
            fixture_dir=TRACER_FIXTURE_DIR,
            event_fixture_dir=EVENT_FIXTURE_DIR,
            campus_fixture_dir=CAMPUS_FIXTURE_DIR,
        )
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'personal-route-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    engine.dispose()
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


def test_personal_route_requires_current_profile_and_sets_anonymous_cookie(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/personal-route")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert "andromeda_profile_session=" in response.headers.get("set-cookie", "")


def test_personal_route_reuses_recommendations_and_enriches_event_points(tmp_path: Path) -> None:
    client = _client(tmp_path)
    saved = client.post("/proftest/results", json=_answers())
    assert saved.status_code == 200, saved.text

    first = client.get("/personal-route", params={"limit": 10})
    second = client.get("/personal-route", params={"limit": 10})

    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    payload = first.json()
    assert payload["status"] == "ready"
    assert len(payload["recommendations"]) >= 2
    assert payload["steps"][0]["kind"] == "explore_program"
    assert payload["steps"][0]["programIds"] == [payload["recommendations"][0]["programId"]]
    assert payload["steps"][1]["kind"] == "compare_programs"
    assert len(payload["steps"][1]["programIds"]) == 2

    event_steps = [step for step in payload["steps"] if step["kind"] == "attend_event"]
    assert event_steps
    assert event_steps[0]["eventId"] == "event:bmstu:dod-2026"
    assert event_steps[0]["startsAt"] == event_steps[0]["event"]["startsAt"]
    assert event_steps[0]["venueId"] == "venue:bmstu:main-campus"
    assert event_steps[0]["point"]["id"] == "venue:bmstu:main-campus"
    online = next(step for step in event_steps if step["eventId"] == "event:bmstu:online-open-lecture-2026")
    assert online["venueId"] is None and online["point"] is None
    assert all("route" not in step and "geometry" not in step and "distance" not in step for step in payload["steps"])


def test_personal_route_isolated_profile_and_limit_validation_are_explicit(tmp_path: Path) -> None:
    first = _client(tmp_path)
    saved = first.post("/proftest/results", json=_answers())
    assert saved.status_code == 200, saved.text
    assert first.get("/personal-route", params={"limit": 0}).status_code == 422
    assert first.get("/personal-route", params={"limit": 21}).status_code == 422

    isolated = _client(tmp_path / "isolated")
    missing = isolated.get("/personal-route")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
