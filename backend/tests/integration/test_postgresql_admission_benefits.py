from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alembic import command
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.database.models import (
    AdmissionBenefitIngestionCoverageModel,
    AdmissionBenefitRuleModel,
    IndividualAchievementRuleModel,
)
from andromeda.infrastructure.repositories.admission_benefits import (
    SqlAlchemyAdmissionBenefitsRepository,
)
from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter

BACKEND_ROOT = Path(__file__).parents[2]
TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
BENEFIT_FIXTURE_DIR = Path(__file__).parents[1] / "ingestion" / "fixtures" / "bmstu" / "admission_benefits"


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


def _benefit_snapshot(file_name: str, document_kind: str) -> RawSourceSnapshot:
    payload = json.loads((BENEFIT_FIXTURE_DIR / file_name).read_text(encoding="utf-8"))
    url = payload["source_url"]
    return RawSourceSnapshot(
        source_kind=f"bmstu_admission_document:{document_kind}",
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="application/json",
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_sha256=payload["content_sha256"],
        body=(BENEFIT_FIXTURE_DIR / file_name).read_bytes(),
        access_mode="fixture",
    )


def test_postgresql_persists_and_reads_bmstu_admission_benefits() -> None:
    database_url = _postgres_url()
    run_id = f"ingest:{uuid4().hex}"
    adapter = BmstuUniversityAdapter()
    try:
        captured = adapter.capture(
            mode="fixture",
            fixture_dir=TRACER_FIXTURE_DIR,
            admission_benefits_fixture_dir=BENEFIT_FIXTURE_DIR,
            admission_year=2026,
        )
        raw, canonical = adapter.parse(captured, source_run_id=run_id, admission_year=2026)
    finally:
        adapter.close()

    assert canonical.admission_benefits is not None
    assert canonical.admission_benefits.benefit_rules
    assert canonical.admission_benefits.individual_achievement_policy is not None

    _migrate(database_url)
    engine = create_engine_for_url(database_url)
    try:
        repository = SqlAlchemyIngestionRepository(engine)
        repository.start_run(run_id=run_id, university_id=canonical.university.id)
        repository.ingest(raw, canonical, run_id=run_id)

        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(AdmissionBenefitRuleModel)) > 0
            assert session.scalar(select(func.count()).select_from(IndividualAchievementRuleModel)) > 0
            catalog = SqlAlchemyAdmissionBenefitsRepository(session).get_catalog("university:bmstu", 2026)
            assert catalog is not None
            assert catalog.benefit_rules
            assert catalog.individual_achievement_policy is not None
            assert catalog.coverage.manifest_hash is not None
            assert session.scalar(select(func.count()).select_from(AdmissionBenefitIngestionCoverageModel)) == 1
    finally:
        engine.dispose()
