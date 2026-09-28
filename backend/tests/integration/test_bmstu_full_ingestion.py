from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.database.models import (
    AdmissionOfferingModel,
    AdmissionPassingScoreModel,
    DisciplineModel,
    IngestRunModel,
    ProgramModel,
    SourceSnapshotModel,
)

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from run_andromeda_bmstu import run_ingest  # noqa: E402


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def test_bmstu_fixture_ingestion_is_repeatable_and_reports_quality_counts(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'bmstu-full-ingestion.db').as_posix()}"
    first = run_ingest(
        mode="fixture",
        fixture_dir=FIXTURE_DIR,
        database_url=database_url,
        program_codes=(),
    )
    second = run_ingest(
        mode="fixture",
        fixture_dir=FIXTURE_DIR,
        database_url=database_url,
        program_codes=(),
    )

    assert first.program_ids == second.program_ids == ("program:bmstu:09.03.01-02", "program:bmstu:09.03.01-12")
    assert first.profile_count == second.profile_count == 2
    assert first.unique_plan_count == second.unique_plan_count == 2
    assert first.canonical_offering_count == second.canonical_offering_count
    assert first.unique_discipline_count == second.unique_discipline_count == 101
    assert first.order_manifest_count == second.order_manifest_count == 0
    assert first.order_document_count == second.order_document_count == 0

    engine = create_engine_for_url(database_url)
    try:
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(ProgramModel)) == first.profile_count
            assert session.scalar(select(func.count()).select_from(AdmissionOfferingModel)) == first.canonical_offering_count
            assert session.scalar(select(func.count()).select_from(DisciplineModel)) == first.unique_discipline_count
            assert session.scalar(select(func.count()).select_from(SourceSnapshotModel)) == first.source_count
            assert session.scalar(select(func.count()).select_from(AdmissionPassingScoreModel)) > 0
            assert session.scalar(select(func.count()).select_from(IngestRunModel)) == 2
    finally:
        engine.dispose()
