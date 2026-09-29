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
    database_url = f"sqlite:///{(tmp_path / 'profile-api.db').as_posix()}"
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


def test_missing_profile_is_not_found_and_sets_anonymous_cookie(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/proftest/profile")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert "andromeda_profile_session=" in response.headers.get("set-cookie", "")


def test_results_persist_current_profile_and_current_recommendations_reuse_it(tmp_path: Path) -> None:
    client = _client(tmp_path)

    results = client.post("/proftest/results", json=_answers())
    assert results.status_code == 200, results.text
    profile = results.json()["profile"]

    stored = client.get("/proftest/profile")
    current = client.get("/recommendations/current", params={"limit": 2})

    assert stored.status_code == 200, stored.text
    assert stored.json()["profile"] == profile
    assert stored.json()["revision"] == 1
    assert current.status_code == 200, current.text
    assert current.json()["profile"] == profile
    assert len(current.json()["recommendations"]) == 2


def test_profile_create_update_and_stale_revision_are_explicit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    profile = client.post("/proftest/results", json=_answers()).json()["profile"]

    duplicate = client.post("/proftest/profile", json={"profile": profile})
    updated = client.put("/proftest/profile", json={"profile": profile, "expectedRevision": 1})
    stale = client.put("/proftest/profile", json={"profile": profile, "expectedRevision": 1})

    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "CONFLICT"
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert stale.status_code == 409
    assert stale.json()["code"] == "CONFLICT"


def test_profile_endpoints_reject_unknown_fields(tmp_path: Path) -> None:
    client = _client(tmp_path)
    profile = client.post("/proftest/results", json=_answers()).json()["profile"]

    response = client.put(
        "/proftest/profile",
        json={"profile": profile, "expectedRevision": 1, "unexpected": True},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
