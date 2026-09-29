from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from andromeda.api.main import create_app
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.repositories.user_profiles import SqlAlchemyUserProfileRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.modules.proftest.contracts.public import ProfileScope, UserProfile


BACKEND_ROOT = Path(__file__).parents[2]


def _postgres_url() -> str:
    value = os.environ.get("ANDROMEDA_POSTGRES_TEST_URL") or os.environ.get("BMSTU_DATABASE_URL")
    if not value or not value.startswith(("postgresql://", "postgresql+")):
        pytest.skip("PostgreSQL test DSN is not configured")
    return value


def _migrate(database_url: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def test_postgresql_persists_user_profile_through_repository_and_api() -> None:
    database_url = _postgres_url()
    _migrate(database_url)
    engine = create_engine_for_url(database_url)
    try:
        assert "user_profiles" in inspect(engine).get_table_names()
        adapter = BmstuUniversityAdapter()
        try:
            raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
        finally:
            adapter.close()
        from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository

        SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            repository = SqlAlchemyUserProfileRepository(session)
            scope = ProfileScope(session_key_hash="f" * 64)
            snapshot = repository.create(scope, UserProfile(), expires_at=datetime.now(timezone.utc) + timedelta(days=1))
            assert repository.get_current(scope) is not None
            assert snapshot.revision == 1
    finally:
        engine.dispose()

    client = TestClient(create_app(database_url))
    assert client.get("/programs").status_code == 200
