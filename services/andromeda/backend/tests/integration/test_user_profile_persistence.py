from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


BACKEND_ROOT = Path(__file__).parents[2]


def _migrate(database_url: str, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    # The PostgreSQL CI job exports the generic URL globally.  Point Alembic
    # explicitly at this isolated SQLite database instead of relying on the
    # deprecated BMSTU_* fallback.
    monkeypatch.setenv("ANDROMEDA_DATABASE_URL", database_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def _seed(tmp_path: Path, monkeypatch) -> str:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'user-profile-persistence.db').as_posix()}"
    _migrate(database_url, monkeypatch)
    engine = create_engine_for_url(database_url)
    try:
        SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    finally:
        engine.dispose()
    return database_url


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


def test_migration_ingestion_profile_api_and_fresh_process_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_url = _seed(tmp_path, monkeypatch)
    first = TestClient(create_app(database_url))

    saved = first.post("/proftest/results", json=_answers())
    assert saved.status_code == 200, saved.text
    profile = saved.json()["profile"]
    cookie = first.cookies.get("andromeda_profile_session")
    assert cookie is not None

    first.close()
    second = TestClient(create_app(database_url))
    second.cookies.set("andromeda_profile_session", cookie)
    stored = second.get("/proftest/profile")
    recommendations = second.get("/recommendations/current", params={"limit": 2})

    assert stored.status_code == 200, stored.text
    assert stored.json()["profile"] == profile
    assert stored.json()["revision"] == 1
    assert recommendations.status_code == 200, recommendations.text
    assert recommendations.json()["profile"] == profile
    assert len(recommendations.json()["recommendations"]) == 2

    isolated = TestClient(create_app(database_url))
    assert isolated.get("/proftest/profile").status_code == 404
    assert isolated.get("/recommendations/current").status_code == 404


def test_register_binds_anonymous_profile_and_restores_it_for_a_fresh_auth_session(tmp_path: Path, monkeypatch) -> None:
    database_url = _seed(tmp_path, monkeypatch)
    anonymous = TestClient(create_app(database_url))
    saved = anonymous.post("/proftest/results", json=_answers())
    assert saved.status_code == 200, saved.text
    expected_profile = saved.json()["profile"]

    registered = anonymous.post("/auth/register", json={"email": "profile-owner@example.com", "password": "a-secure-password"})
    assert registered.status_code == 201, registered.text
    auth_cookie = anonymous.cookies.get("andromeda_auth_session")
    assert auth_cookie is not None
    anonymous.close()

    fresh = TestClient(create_app(database_url))
    fresh.cookies.set("andromeda_auth_session", auth_cookie)
    restored = fresh.get("/proftest/profile")
    assert restored.status_code == 200, restored.text
    assert restored.json()["profile"] == expected_profile
    fresh.close()
