from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import CurriculumItemModel, IngestRunModel, ProgramModel
from andromeda.shared.contracts.errors import ContractError

BACKEND_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

import run_andromeda_ingestion as runner  # noqa: E402


def test_rejected_quality_snapshot_preserves_last_good_projection(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'quality-gate.db').as_posix()}"
    fixture_dir = BACKEND_ROOT / "tests" / "fixtures" / "tracer" / "raw"

    first = runner.run_university(
        university="bmstu",
        mode="fixture",
        fixture_dir=fixture_dir,
        database_url=database_url,
        program_codes=(),
    )

    source_adapter = runner.create_adapter("bmstu")
    captured = source_adapter.capture(mode="fixture", fixture_dir=fixture_dir)
    raw, canonical = source_adapter.parse(captured)
    source_adapter.close()
    sparse_canonical = canonical.model_copy(
        update={
            "programs": (canonical.programs[0],),
            "curricula": (canonical.curricula[0],),
            "admissions": (canonical.admissions[0],),
        }
    )

    class SparseAdapter:
        def capture(self, *, mode: str, fixture_dir: Path):
            del mode, fixture_dir
            return captured

        def parse(self, captured_sources, *, program_codes=None):
            del captured_sources, program_codes
            return raw, sparse_canonical

        def close(self) -> None:
            return None

    monkeypatch.setattr(runner, "create_adapter", lambda _slug: SparseAdapter())

    try:
        runner.run_university(
            university="bmstu",
            mode="fixture",
            fixture_dir=fixture_dir,
            database_url=database_url,
            program_codes=(),
            minimum_ratio=0.75,
        )
    except ContractError as exc:
        assert "INGESTION_QUALITY_REJECTED" in str(exc)
    else:
        raise AssertionError("a sparse snapshot must be rejected")

    from andromeda.infrastructure.database import create_engine_for_url

    engine = create_engine_for_url(database_url)
    try:
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(ProgramModel)) == len(first.program_ids)
            assert session.scalar(select(func.count()).select_from(CurriculumItemModel)) == first.curriculum_item_count
            runs = session.scalars(select(IngestRunModel).order_by(IngestRunModel.started_at.asc())).all()
            assert [run.status for run in runs] == ["completed", "failed"]
            assert runs[0].quality_status == "degraded"
            quality_metrics = json.loads(runs[0].quality_metrics_json)
            assert quality_metrics["taxonomy_metric_version"] == "taxonomy-metrics.v1"
            assert quality_metrics["taxonomy"]["source_hashes"]
            assert "taxonomy_unresolved_count" in quality_metrics
            assert runs[1].quality_status == "rejected"
            assert runs[1].previous_good_run_id == first.run_id
            assert runs[1].error_code == "CONTRACT_ERROR"
    finally:
        engine.dispose()
