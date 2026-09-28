from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_bmstu_fixture_crosses_ingestion_recommendations_events_and_personal_route_api(tmp_path: Path) -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures"
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(
            fixture_dir=fixture_root / "tracer" / "raw",
            event_fixture_dir=fixture_root / "events" / "raw",
            campus_fixture_dir=fixture_root / "campus" / "raw",
        )
    finally:
        adapter.close()

    database_url = f"sqlite:///{(tmp_path / 'personal-route-vertical.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    client = TestClient(create_app(database_url))
    answers = {
        "answers": [
            {"questionId": "interest_free_day", "optionIds": ["software_tool"]},
            {"questionId": "interest_investigation", "optionIds": ["prove_model"]},
            {"questionId": "activity_build", "optionIds": ["system_scheme"]},
            {"questionId": "activity_working_style", "optionIds": ["analyze_options"]},
            {"questionId": "anti_subjects", "optionIds": ["avoid_physics"], "intensity": 0.9},
            {"questionId": "activity_depth", "optionIds": ["practical_prototype"]},
        ]
    }

    profile = client.post("/proftest/results", json=answers)
    response = client.get("/personal-route", params={"limit": 10})

    assert profile.status_code == 200, profile.text
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["recommendations"]
    assert payload["steps"][0]["kind"] == "explore_program"
    event_steps = [step for step in payload["steps"] if step["kind"] == "attend_event"]
    assert event_steps
    assert event_steps[0]["event"]["programIds"]
    assert event_steps[0]["point"]["id"] == event_steps[0]["venueId"]


def test_personal_route_postgresql_flow_uses_current_profile_and_existing_points() -> None:
    import os

    database_url = os.environ.get("ANDROMEDA_POSTGRES_TEST_URL")
    if not database_url or not database_url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("ANDROMEDA_POSTGRES_TEST_URL is not configured")

    fixture_root = Path(__file__).parents[1] / "fixtures"
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(
            fixture_dir=fixture_root / "tracer" / "raw",
            event_fixture_dir=fixture_root / "events" / "raw",
            campus_fixture_dir=fixture_root / "campus" / "raw",
        )
    finally:
        adapter.close()
    engine = create_engine_for_url(database_url)
    try:
        SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    finally:
        engine.dispose()

    client = TestClient(create_app(database_url))
    profile = client.post(
        "/proftest/results",
        json={
            "answers": [
                {"questionId": "interest_free_day", "optionIds": ["software_tool"]},
                {"questionId": "interest_investigation", "optionIds": ["prove_model"]},
                {"questionId": "activity_build", "optionIds": ["system_scheme"]},
                {"questionId": "activity_working_style", "optionIds": ["analyze_options"]},
                {"questionId": "anti_subjects", "optionIds": ["avoid_physics"], "intensity": 0.9},
                {"questionId": "activity_depth", "optionIds": ["practical_prototype"]},
            ]
        },
    )
    response = client.get("/personal-route")

    assert profile.status_code == 200, profile.text
    assert response.status_code == 200, response.text
    assert response.json()["recommendations"]
