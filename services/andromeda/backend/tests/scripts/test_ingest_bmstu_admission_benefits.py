from __future__ import annotations

from pathlib import Path

from scripts.ingest_bmstu_admission_benefits import run

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
BENEFIT_FIXTURE_DIR = Path(__file__).parents[1] / "ingestion" / "fixtures" / "bmstu" / "admission_benefits"


def test_fixture_dry_run_returns_source_coverage_without_database_write(tmp_path: Path) -> None:
    report = run(
        mode="fixture",
        year=2026,
        fixture_dir=FIXTURE_DIR,
        benefit_fixture_dir=BENEFIT_FIXTURE_DIR,
        database_url=f"sqlite:///{(tmp_path / 'should-not-be-created.db').as_posix()}",
        dry_run=True,
        allow_partial=True,
    )
    assert report.dry_run is True
    assert report.documents_captured == 6
    assert report.bvi_rules > 0
    assert report.individual_achievement_rules > 0
    assert not (tmp_path / "should-not-be-created.db").exists()


def test_partial_fixture_is_rejected_before_persistence_without_override(tmp_path: Path) -> None:
    try:
        run(
            mode="fixture",
            year=2026,
            fixture_dir=FIXTURE_DIR,
            benefit_fixture_dir=BENEFIT_FIXTURE_DIR,
            database_url=f"sqlite:///{(tmp_path / 'partial.db').as_posix()}",
            dry_run=True,
            allow_partial=False,
        )
    except Exception as exc:  # noqa: BLE001 - CLI contract intentionally accepts its typed validation error.
        assert "partial" in str(exc).casefold()
    else:
        raise AssertionError("partial fixture must require an explicit override")
