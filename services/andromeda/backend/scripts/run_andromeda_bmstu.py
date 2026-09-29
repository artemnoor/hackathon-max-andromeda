"""Canonical BMSTU fixture/live verification runner.

The runner owns the source-backed BMSTU capture, validation and projection
flow. ``run_tracer_bullet.py`` remains only as a one-cycle import/CLI
compatibility wrapper for existing local scripts and tests.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from alembic import command
from alembic.config import Config

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.composition import build_container  # noqa: E402
from andromeda.ingestion.contracts.normalized import CanonicalSnapshot  # noqa: E402
from andromeda.ingestion.contracts.raw import RawTracerBundle  # noqa: E402
from andromeda.ingestion.universities.bmstu import (  # noqa: E402
    DEFAULT_CAMPUS_FIXTURE_DIR,
    DEFAULT_EVENT_FIXTURE_DIR,
    DEFAULT_FIXTURE_DIR,
    BmstuUniversityAdapter,
)
from andromeda.ingestion.universities.bmstu.capture import AdmissionOrderManifestEntry, parse_orders_manifest  # noqa: E402
from andromeda.ingestion.universities.bmstu.parser.admission_orders import iter_pdf_pages  # noqa: E402
from andromeda.ingestion.universities.bmstu.source_metadata import classify_order_document  # noqa: E402
from andromeda.infrastructure.config import Settings, redact_database_url  # noqa: E402
from andromeda.infrastructure.database import create_engine_for_url  # noqa: E402


logger = logging.getLogger("andromeda.runner.bmstu")
_CONFIGURED_LOG_LEVEL = logging.INFO


@dataclass(frozen=True, slots=True)
class AndromedaRunResult:
    run_id: str
    program_ids: tuple[str, ...]
    curriculum_item_count: int
    source_count: int
    source_hashes: tuple[str, ...]
    event_count: int
    campus_point_count: int = 0
    direction_count: int = 0
    study_plan_count: int = 0
    source_gap_count: int = 0
    catalog_card_count: int = 0
    detail_count: int = 0
    profile_count: int = 0
    unique_plan_count: int = 0
    order_manifest_count: int = 0
    order_document_count: int = 0
    supported_order_document_count: int = 0
    unsupported_order_document_count: int = 0
    order_numeric_count: int = 0
    order_bvi_count: int = 0
    canonical_offering_count: int = 0
    unique_discipline_count: int = 0


def configure_logging(log_level: str) -> None:
    global _CONFIGURED_LOG_LEVEL
    selected_level = os.environ.get("LOG_LEVEL", log_level).upper()
    _CONFIGURED_LOG_LEVEL = getattr(logging, selected_level, logging.INFO)
    logging.basicConfig(level=_CONFIGURED_LOG_LEVEL, format="%(levelname)s %(name)s %(message)s")
    _restore_ingestion_loggers()


def _restore_ingestion_loggers() -> None:
    """Keep Andromeda ingestion diagnostics enabled after Alembic setup."""

    logging.getLogger().setLevel(_CONFIGURED_LOG_LEVEL)
    for name, candidate in logging.Logger.manager.loggerDict.items():
        if name == "andromeda" or name.startswith("andromeda.ingestion"):
            if isinstance(candidate, logging.Logger):
                candidate.disabled = False


def selected_program_codes(
    program_codes: Sequence[str] | None,
    program_ids: Sequence[str] | None,
) -> tuple[str, ...]:
    if program_codes and program_ids:
        raise ValueError("use --program-code or --program-id, not both")
    if program_ids:
        return tuple(value.removeprefix("program:") for value in program_ids)
    return tuple(program_codes) if program_codes else ()


def run_ingest(
    *,
    mode: str,
    fixture_dir: Path,
    event_fixture_dir: Path | None = None,
    campus_fixture_dir: Path | None = None,
    database_url: str,
    program_codes: Sequence[str] | None,
) -> AndromedaRunResult:
    """Run source capture, contract parsing, migration and projection once."""

    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        database_path = Path(database_url.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "ingest_start mode=%s programs=%s database_target=%s",
        mode,
        ",".join(program_codes) if program_codes else "catalog-discovery",
        redact_database_url(database_url),
    )
    settings = Settings.from_environment(database_url)
    engine = create_engine_for_url(database_url, **settings.engine_options)
    container = build_container(engine, settings)
    try:
        migration_config = Config(str(BACKEND_ROOT / "alembic.ini"))
        migration_config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        migration_config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(migration_config, "head")
        _restore_ingestion_loggers()

        source = BmstuUniversityAdapter()
        try:
            raw, normalized = source.parse_sources(
                mode=mode,
                fixture_dir=fixture_dir,
                event_fixture_dir=event_fixture_dir or DEFAULT_EVENT_FIXTURE_DIR,
                campus_fixture_dir=campus_fixture_dir or DEFAULT_CAMPUS_FIXTURE_DIR,
                program_codes=program_codes or None,
            )
        finally:
            source.close()

        _validate_run_invariants(mode, raw, normalized)
        run_id = container.ingestion.ingest(raw, normalized)
        order_counts = _order_counts(raw)
        result = AndromedaRunResult(
            run_id=run_id,
            program_ids=tuple(program.id for program in normalized.programs),
            curriculum_item_count=sum(len(curriculum.items) for curriculum in normalized.curricula),
            source_count=len(normalized.sources),
            source_hashes=tuple(source.content_sha256 for source in normalized.sources),
            event_count=len(normalized.events),
            campus_point_count=len(normalized.campus_points),
            direction_count=len(normalized.directions or (normalized.direction,)),
            study_plan_count=len(normalized.curricula),
            source_gap_count=len(normalized.source_gaps),
            catalog_card_count=_catalog_card_count(raw),
            detail_count=sum(1 for snapshot in raw.snapshots if snapshot.source_kind == "bmstu_major_detail"),
            profile_count=len(raw.programs),
            unique_plan_count=len(
                {
                    str(snapshot.requested_url)
                    for snapshot in raw.snapshots
                    if snapshot.source_kind == "bmstu_curriculum_document"
                }
            ),
            order_manifest_count=order_counts[0],
            order_document_count=order_counts[1],
            supported_order_document_count=order_counts[2],
            unsupported_order_document_count=order_counts[3],
            order_numeric_count=order_counts[4],
            order_bvi_count=order_counts[5],
            canonical_offering_count=sum(len(item.offerings) for item in normalized.admissions),
            unique_discipline_count=len(normalized.disciplines),
        )
        logger.info(
            "ingest_complete run_id=%s programs=%d curriculum_items=%d sources=%d events=%d campus_points=%d directions=%d plans=%d order_documents=%d order_numeric=%d order_bvi=%d source_gaps=%d",
            result.run_id,
            len(result.program_ids),
            result.curriculum_item_count,
            result.source_count,
            result.event_count,
            result.campus_point_count,
            result.direction_count,
            result.unique_plan_count,
            result.order_document_count,
            result.order_numeric_count,
            result.order_bvi_count,
            result.source_gap_count,
        )
        return result
    finally:
        engine.dispose()


def result_payload(result: AndromedaRunResult, database_url: str) -> dict[str, object]:
    return {
        "runId": result.run_id,
        "programIds": list(result.program_ids),
        "curriculumItemCount": result.curriculum_item_count,
        "sourceCount": result.source_count,
        "sourceHashes": list(result.source_hashes),
        "eventCount": result.event_count,
        "campusPointCount": result.campus_point_count,
        "directionCount": result.direction_count,
        "studyPlanCount": result.study_plan_count,
        "sourceGapCount": result.source_gap_count,
        "catalogCardCount": result.catalog_card_count,
        "detailCount": result.detail_count,
        "profileCount": result.profile_count,
        "uniquePlanCount": result.unique_plan_count,
        "orderManifestCount": result.order_manifest_count,
        "orderDocumentCount": result.order_document_count,
        "supportedOrderDocumentCount": result.supported_order_document_count,
        "unsupportedOrderDocumentCount": result.unsupported_order_document_count,
        "orderNumericCount": result.order_numeric_count,
        "orderBviCount": result.order_bvi_count,
        "canonicalOfferingCount": result.canonical_offering_count,
        "uniqueDisciplineCount": result.unique_discipline_count,
        "databaseTarget": redact_database_url(database_url),
        "api": {
            "docs": "/docs",
            "openapi": "/openapi.json",
            "program": "/programs/{id}",
            "curriculum": "/programs/{id}/curriculum",
            "admissions": "/programs/{id}/admissions",
            "compare": "/compare?programIds={programIdA},{programIdB}",
            "events": "/events",
            "campusPoints": "/campus/points",
            "campusRecommendations": "/campus/recommendations",
        },
        "frontend": "http://localhost:3000/",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest official BMSTU data through canonical Andromeda contracts")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--event-fixture-dir", type=Path, default=DEFAULT_EVENT_FIXTURE_DIR)
    parser.add_argument("--campus-fixture-dir", type=Path, default=DEFAULT_CAMPUS_FIXTURE_DIR)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--program-code", action="append", dest="program_codes")
    parser.add_argument("--program-id", action="append", dest="program_ids")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def _catalog_card_count(raw: RawTracerBundle) -> int:
    slugs: set[str] = set()
    for snapshot in raw.snapshots:
        if snapshot.source_kind != "bmstu_major_catalog":
            continue
        try:
            payload = json.loads(snapshot.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        values = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and isinstance(item.get("slug"), str):
                slugs.add(item["slug"])
    return len(slugs)


def _order_counts(raw: RawTracerBundle) -> tuple[int, int, int, int, int, int]:
    manifest = next((snapshot for snapshot in raw.snapshots if snapshot.source_kind == "bmstu_admission_orders_index"), None)
    documents = tuple(snapshot for snapshot in raw.snapshots if snapshot.source_kind == "bmstu_admission_orders_document")
    manifest_count = 0
    entries_by_url: dict[str, AdmissionOrderManifestEntry] = {}
    if manifest is not None:
        entries = parse_orders_manifest(manifest.body, str(manifest.requested_url))
        manifest_count = len(entries)
        entries_by_url = {entry.requested_url: entry for entry in entries}
    supported = 0
    unsupported = 0
    for snapshot in documents:
        entry = entries_by_url.get(str(snapshot.requested_url))
        if entry is None:
            continue
        if classify_order_document(entry, iter_pdf_pages(snapshot.body)).supported_catalog:
            supported += 1
        else:
            unsupported += 1
    numeric = sum(
        1
        for record in raw.admissions
        if record.source_kind == "bmstu_admission_orders_document"
        for score in record.passing_scores
        if score.status == "numeric"
    )
    bvi = sum(
        1
        for record in raw.admissions
        if record.source_kind == "bmstu_admission_orders_document"
        for score in record.passing_scores
        if score.status == "bvi"
    )
    return manifest_count, len(documents), supported, unsupported, numeric, bvi


def _validate_run_invariants(mode: str, raw: RawTracerBundle, canonical: CanonicalSnapshot) -> None:
    if len({program.id for program in canonical.programs}) != len(canonical.programs):
        raise ValueError("canonical program IDs are not unique")
    if len({direction.id for direction in (canonical.directions or (canonical.direction,))}) != len(canonical.directions or (canonical.direction,)):
        raise ValueError("canonical direction IDs are not unique")
    if any(not snapshot.content_sha256 for snapshot in raw.snapshots):
        raise ValueError("captured source snapshot is missing content hash")
    for discipline in canonical.disciplines:
        if not discipline.area_weights or sum(weight.weight for weight in discipline.area_weights) != 1:
            raise ValueError(f"invalid area weights for {discipline.id}")
    for record in raw.admissions:
        for score in record.passing_scores:
            if score.status == "numeric" and score.score is None:
                raise ValueError("numeric passing score is missing score")
            if score.status == "bvi" and score.score is not None:
                raise ValueError("BVI passing score contains numeric score")
    if mode == "live" and (canonical.events or canonical.campus_points):
        raise ValueError("live ingestion cannot use fixture events or campus points")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    try:
        program_codes = selected_program_codes(args.program_codes, args.program_ids)
    except ValueError as exc:
        raise SystemExit(f"argument error: {exc}") from exc
    database_url = Settings.from_environment(args.database_url).database_url
    result = run_ingest(
        mode=args.mode,
        fixture_dir=args.fixture_dir,
        event_fixture_dir=args.event_fixture_dir,
        campus_fixture_dir=args.campus_fixture_dir,
        database_url=database_url,
        program_codes=program_codes,
    )
    print(json.dumps(result_payload(result, database_url), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AndromedaRunResult",
    "build_parser",
    "configure_logging",
    "main",
    "result_payload",
    "run_ingest",
    "selected_program_codes",
]
