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
TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
CAMPUS_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "campus" / "raw"


def test_campus_reaches_api_after_alembic_head_and_rerun(tmp_path: Path, monkeypatch) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=TRACER_FIXTURE_DIR, campus_fixture_dir=CAMPUS_FIXTURE_DIR)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'campus-migrated.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    # CI's PostgreSQL job also exports the new generic URL.  Use the generic
    # name here so Alembic and the repository target the same test database;
    # legacy BMSTU_* fallback is covered by the configuration tests.
    monkeypatch.setenv("ANDROMEDA_DATABASE_URL", database_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.ingest(raw, canonical)
    repository.ingest(raw, canonical)

    client = TestClient(create_app(database_url))
    response = client.get("/campus/points", params={"pointType": "building"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == "venue:bmstu:main-campus"
