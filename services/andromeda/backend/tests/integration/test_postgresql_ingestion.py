from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alembic import command
from andromeda.infrastructure.database.models import (
    CurriculumItemModel,
    IngestRunModel,
    ProgramModel,
)
from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter

BACKEND_ROOT = Path(__file__).parents[2]


def _postgres_url() -> str:
    url = os.environ.get("ANDROMEDA_POSTGRES_TEST_URL")
    if not url or not url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("ANDROMEDA_POSTGRES_TEST_URL is not configured")
    return url


def _migrate(database_url: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def test_postgresql_ingest_is_repeatable_and_updates_projection() -> None:
    database_url = _postgres_url()
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()

    from andromeda.infrastructure.database import create_engine_for_url

    engine = create_engine_for_url(database_url)
    try:
        _migrate(database_url)
        repository = SqlAlchemyIngestionRepository(engine)
        with Session(engine) as session:
            initial_ingest_run_count = session.scalar(
                select(func.count()).select_from(IngestRunModel)
            )
        repository.ingest(raw, canonical)
        repository.ingest(raw, canonical)

        shortened = canonical.curricula[0].model_copy(update={"items": canonical.curricula[0].items[:-1]})
        updated = canonical.model_copy(
            update={
                "programs": (canonical.programs[0].model_copy(update={"name": "PostgreSQL sync check"}), *canonical.programs[1:]),
                "curricula": (shortened, *canonical.curricula[1:]),
            }
        )
        repository.ingest(raw, updated)

        with Session(engine) as session:
            assert session.scalar(
                select(func.count()).select_from(IngestRunModel)
            ) == initial_ingest_run_count + 3
            assert session.get(ProgramModel, canonical.programs[0].id).name == "PostgreSQL sync check"
            assert session.scalar(
                select(func.count()).select_from(CurriculumItemModel).where(CurriculumItemModel.curriculum_id == canonical.curricula[0].id)
            ) == len(shortened.items)
    finally:
        engine.dispose()
