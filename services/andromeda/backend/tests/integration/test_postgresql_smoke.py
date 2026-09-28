from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_postgresql_supports_the_existing_api_vertical_slice() -> None:
    database_url = os.environ.get("ANDROMEDA_POSTGRES_TEST_URL")
    if not database_url or not database_url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("ANDROMEDA_POSTGRES_TEST_URL is not configured")

    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()

    engine = create_engine_for_url(database_url)
    try:
        SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    finally:
        engine.dispose()

    client = TestClient(create_app(database_url))
    programs = client.get("/programs")
    curriculum = client.get("/programs/program:09.03.01-02/curriculum")
    admissions = client.get("/programs/program:09.03.01-02/admissions")
    events = client.get("/events", params={"format": "online"})
    comparison = client.get(
        "/compare",
        params={"programIds": "program:09.03.01-02,program:09.03.01-12", "scope": "semester", "semester": 1},
    )
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
    proftest = client.post("/proftest/results", json=answers)
    admission_payload = admissions.json()
    admission_offering = next(item for item in admission_payload["offerings"] if item["exams"])
    admission_fit = client.post(
        "/programs/program:09.03.01-02/admission-fit",
        json={
            "offeringId": admission_offering["id"],
            "applicant": {
                "scores": [
                    {"subject": exam["subject"], "score": 90}
                    for exam in admission_offering["exams"]
                ]
            },
        },
    )

    assert programs.status_code == 200
    assert len(programs.json()["items"]) == 2
    assert curriculum.status_code == 200
    assert admissions.status_code == 200
    assert events.status_code == 200
    assert events.json()["items"][0]["id"] == "event:bmstu:online-open-lecture-2026"
    assert curriculum.json()["items"]
    assert comparison.status_code == 200
    assert comparison.json()["rows"]
    assert proftest.status_code == 200
    assert admission_fit.status_code == 200
    assert admission_fit.json()["programId"] == "program:bmstu:09.03.01-02"
    profile = proftest.json()["profile"]
    recommendations = client.post("/recommendations", json={"profile": profile, "limit": 2})
    assert recommendations.status_code == 200
    assert len(recommendations.json()["recommendations"]) == 2


def test_postgresql_supports_protected_admin_ops_retry(monkeypatch) -> None:
    database_url = os.environ.get("ANDROMEDA_POSTGRES_TEST_URL")
    if not database_url or not database_url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("ANDROMEDA_POSTGRES_TEST_URL is not configured")

    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", "postgres-admin-ops-test-key")
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()

    engine = create_engine_for_url(database_url)
    try:
        SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    finally:
        engine.dispose()

    client = TestClient(create_app(database_url))
    response = client.post(
        "/ops/ingestion/runs/retry",
        json={"source": "bmstu_fixture"},
        headers={"X-Andromeda-Ops-Key": "postgres-admin-ops-test-key"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["run"]["status"] == "completed"
    assert "body" not in response.text
    assert "payload_json" not in response.text


def test_postgresql_supports_the_campus_data_contract() -> None:
    database_url = os.environ.get("ANDROMEDA_POSTGRES_TEST_URL")
    if not database_url or not database_url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("ANDROMEDA_POSTGRES_TEST_URL is not configured")

    fixture_root = Path(__file__).parents[1]
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(
            fixture_dir=fixture_root / "fixtures" / "tracer" / "raw",
            campus_fixture_dir=fixture_root / "fixtures" / "campus" / "raw",
        )
    finally:
        adapter.close()

    engine = create_engine_for_url(database_url)
    try:
        SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    finally:
        engine.dispose()

    client = TestClient(create_app(database_url))
    points = client.get("/campus/points", params={"universityId": "university:bmstu", "limit": 100})
    detail = client.get("/campus/points/venue:bmstu:main-campus")
    events = client.get("/campus/points/venue:bmstu:main-campus/events")

    assert points.status_code == 200
    assert points.json()["total"] >= 5
    assert {item["pointType"] for item in points.json()["items"]} >= {
        "building",
        "room_zone",
        "event_venue",
        "entrance",
        "other",
    }
    assert detail.status_code == 200
    assert detail.json()["programs"]
    assert events.status_code == 200
    assert events.json()["items"]
