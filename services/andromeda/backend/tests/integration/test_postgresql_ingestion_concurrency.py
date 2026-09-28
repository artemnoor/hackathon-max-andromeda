from __future__ import annotations

import concurrent.futures
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.database.models import IngestRunModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.infrastructure.repositories.ingestion_recovery import SqlAlchemyIngestionRunRecovery
from andromeda.shared.contracts.errors import ConflictError


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _postgres_url() -> str:
    url = os.environ.get("ANDROMEDA_POSTGRES_TEST_URL")
    if not url or not url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("ANDROMEDA_POSTGRES_TEST_URL is not configured")
    return url


def _migrate(database_url: str) -> None:
    config = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND_ROOT, "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def test_postgresql_enforces_scoped_active_identity_across_workers() -> None:
    database_url = _postgres_url()
    _migrate(database_url)
    engine = create_engine_for_url(database_url, pool_size=4, max_overflow=0)
    suffix = uuid4().hex
    university_id = f"university:concurrency:{suffix[:20]}"
    source_profile = f"concurrency:{suffix}"

    def attempt() -> tuple[str, str]:
        repository = SqlAlchemyIngestionRepository(engine)
        try:
            return "created", repository.start_run(university_id=university_id, source_profile=source_profile)
        except ConflictError as exc:
            assert exc.details
            return "conflict", exc.details[0].message

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: attempt(), (1, 2)))

        assert sorted(result[0] for result in results) == ["conflict", "created"]
        created_id = next(result[1] for result in results if result[0] == "created")
        conflict_id = next(result[1] for result in results if result[0] == "conflict")
        assert conflict_id == created_id

        second_university = f"university:other:{suffix[:20]}"
        other_id = SqlAlchemyIngestionRepository(engine).start_run(
            university_id=second_university,
            source_profile=source_profile,
        )
        assert other_id != created_id
    finally:
        engine.dispose()


def test_postgresql_idempotency_and_lease_recovery_are_auditable() -> None:
    database_url = _postgres_url()
    _migrate(database_url)
    engine = create_engine_for_url(database_url)
    suffix = uuid4().hex
    repository = SqlAlchemyIngestionRepository(engine)
    first = repository.start_run(
        university_id=f"university:recovery:{suffix[:20]}",
        source_profile=f"recovery:{suffix}",
        idempotency_key=f"recovery-key:{suffix}",
    )
    assert repository.start_run(
        university_id="university:unexpected",
        source_profile="recovery:unexpected",
        idempotency_key=f"recovery-key:{suffix}",
    ) == first

    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        row = session.scalar(select(IngestRunModel).where(IngestRunModel.id == first))
        assert row is not None
        row.heartbeat_at = now - timedelta(hours=2)
        session.commit()

    assert SqlAlchemyIngestionRunRecovery(engine).recover_stale(timeout_seconds=60, now=now) == (first,)
    with Session(engine) as session:
        row = session.get(IngestRunModel, first)
        assert row is not None
        assert row.status == "failed"
        assert row.error_code == "INGESTION_STALE_TIMEOUT"
        assert row.recovery_reason == "lease_expired_before_terminal_update"
    engine.dispose()
