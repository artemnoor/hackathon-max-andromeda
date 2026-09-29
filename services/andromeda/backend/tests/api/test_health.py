from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from andromeda.api.main import create_app
from andromeda.api.routes.health import expected_schema_revision


BACKEND_ROOT = Path(__file__).parents[2]


def _migrate(database_url: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def test_live_is_process_probe_and_ready_requires_current_schema(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    database_url = f"sqlite:///{(tmp_path / 'health.db').as_posix()}"
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    _migrate(database_url)

    client = TestClient(create_app(database_url))
    assert client.get("/health/live").json() == {"status": "live"}
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "schema": expected_schema_revision(),
        "expectedSchema": expected_schema_revision(),
        "database": "ok",
    }


def test_ready_rejects_schema_behind_and_missing_database_schema(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    database_url = f"sqlite:///{(tmp_path / 'health-mismatch.db').as_posix()}"
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    _migrate(database_url)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = '0016_ingestion_source_health'"))
    finally:
        engine.dispose()

    mismatch = TestClient(create_app(database_url)).get("/health/ready")
    assert mismatch.status_code == 503
    assert mismatch.json()["reason"] == "schema_mismatch"
    assert mismatch.json()["expectedSchema"] == expected_schema_revision()

    missing_url = f"sqlite:///{(tmp_path / 'health-missing.db').as_posix()}"
    missing = TestClient(create_app(missing_url)).get("/health/ready")
    assert missing.status_code == 503
    assert missing.json()["reason"] == "database_unavailable"
