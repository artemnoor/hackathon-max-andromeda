"""Refresh BMSTU admission-benefit facts through the existing ingestion path."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from alembic.config import Config

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.composition import build_container
from andromeda.infrastructure.config import Settings, redact_database_url
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.ingestion.contracts.normalized import CanonicalSnapshot
from andromeda.ingestion.contracts.raw import RawTracerBundle
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.shared.contracts.errors import ContractError, ErrorCode

logger = logging.getLogger("andromeda.bmstu_admission_benefits_runner")


@dataclass(frozen=True, slots=True)
class AdmissionBenefitsRunReport:
    admission_year: int
    run_id: str | None
    documents_discovered: int
    documents_captured: int
    documents_parsed: int
    olympiads_parsed: int
    olympiad_profiles: int
    bvi_rules: int
    hundred_point_rules: int
    individual_achievement_rules: int
    directions_resolved: int
    directions_unresolved: int
    conflicts: int
    source_gaps: int
    dry_run: bool


def _migrate(database_url: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def _validate(canonical: CanonicalSnapshot) -> None:
    snapshot = canonical.admission_benefits
    if snapshot is None:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "No BMSTU admission-benefit documents were parsed")
    if not snapshot.benefit_rules and snapshot.individual_achievement_policy is None:
        raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "BMSTU admission-benefit snapshot contains no canonical rules")
    for rule in snapshot.benefit_rules:
        if rule.status.value == "active" and rule.scope.unresolved_targets:
            raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Active admission-benefit rule contains unresolved scope")


def run(
    *,
    mode: str,
    year: int,
    fixture_dir: Path | None,
    benefit_fixture_dir: Path | None,
    database_url: str | None,
    dry_run: bool,
    allow_partial: bool,
) -> AdmissionBenefitsRunReport:
    settings = Settings.from_environment(database_url)
    engine = None
    run_id: str | None = None
    if not dry_run:
        _migrate(settings.database_url)
        engine = create_engine_for_url(settings.database_url, **settings.engine_options)
        container = build_container(engine, settings)
        run_id = container.ingestion.start_run(
            source_profile=f"bmstu:admission-benefits:{mode}:cli:v1",
            source_revision=f"bmstu-admission-documents-{year}",
            configuration_version="admission-benefits-cli.v1",
            university_id="university:bmstu",
        )
    else:
        container = None

    adapter = BmstuUniversityAdapter()
    try:
        captured = adapter.capture(
            mode=mode,
            fixture_dir=fixture_dir,
            admission_benefits_fixture_dir=benefit_fixture_dir,
            admission_year=year,
            include_admission_benefits=True,
        )
        if run_id is not None:
            assert container is not None
            container.ingestion.record_captured_metadata(run_id, captured)
        raw, canonical = adapter.parse(
            captured,
            source_run_id=run_id,
            admission_year=year,
        )
        _validate(canonical)
        snapshot = canonical.admission_benefits
        assert snapshot is not None
        report = _report(canonical, raw, run_id=run_id, dry_run=dry_run)
        if not allow_partial and (report.source_gaps or report.directions_unresolved):
            raise ContractError(
                ErrorCode.SOURCE_CONTRACT_ERROR,
                "BMSTU admission-benefit refresh is partial; inspect coverage report or pass --allow-partial",
            )
        if run_id is not None:
            assert container is not None
            container.ingestion.record_source_metadata(run_id, raw)
            container.ingestion.ingest(raw, canonical, run_id=run_id)
        logger.info(
            "bmstu_admission_benefits_refresh_complete year=%d run_id=%s rules=%d achievements=%d gaps=%d dry_run=%s",
            year,
            run_id,
            report.bvi_rules + report.hundred_point_rules,
            report.individual_achievement_rules,
            report.source_gaps,
            dry_run,
        )
        return report
    except Exception as exc:  # noqa: BLE001 - CLI boundary must report every failed refresh safely.
        if run_id is not None and container is not None:
            container.ingestion.mark_failed(run_id, exc)
        raise
    finally:
        adapter.close()
        if engine is not None:
            engine.dispose()


def _report(canonical: CanonicalSnapshot, raw: RawTracerBundle, *, run_id: str | None, dry_run: bool) -> AdmissionBenefitsRunReport:
    snapshot = canonical.admission_benefits
    assert snapshot is not None
    coverage = snapshot.coverage
    bvi_rules = sum(rule.benefit_type.value == "bvi" for rule in snapshot.benefit_rules)
    hundred_rules = sum(rule.benefit_type.value == "one_hundred_points" for rule in snapshot.benefit_rules)
    return AdmissionBenefitsRunReport(
        admission_year=snapshot.admission_year,
        run_id=run_id,
        documents_discovered=coverage.documents_discovered,
        documents_captured=coverage.documents_captured,
        documents_parsed=coverage.documents_parsed,
        olympiads_parsed=len(snapshot.olympiads),
        olympiad_profiles=len(snapshot.olympiad_profiles),
        bvi_rules=bvi_rules,
        hundred_point_rules=hundred_rules,
        individual_achievement_rules=len(snapshot.individual_achievement_policy.rules) if snapshot.individual_achievement_policy else 0,
        directions_resolved=coverage.targets_resolved,
        directions_unresolved=coverage.unresolved_targets,
        conflicts=coverage.conflicts,
        source_gaps=len(raw.source_gaps) + len(snapshot.source_gaps),
        dry_run=dry_run,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest official BMSTU admission-benefit rules for one admission year")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--fixture-dir", type=Path, help="Existing BMSTU catalog fixture directory")
    parser.add_argument("--benefit-fixture-dir", type=Path, help="BMSTU admission-document fixture directory")
    parser.add_argument("--database-url")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s %(message)s")
    try:
        report = run(
            mode=args.mode,
            year=args.year,
            fixture_dir=args.fixture_dir,
            benefit_fixture_dir=args.benefit_fixture_dir,
            database_url=args.database_url,
            dry_run=args.dry_run,
            allow_partial=args.allow_partial,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports every failed refresh safely.
        logger.error("bmstu_admission_benefits_refresh_failed exception_type=%s message=%s", type(exc).__name__, str(exc)[:256])
        return 1
    print(
        json.dumps(
            {"report": asdict(report), "databaseTarget": redact_database_url(Settings.from_environment(args.database_url).database_url)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
