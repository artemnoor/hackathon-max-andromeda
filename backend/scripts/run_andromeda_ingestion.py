"""Generic Andromeda ingestion runner for one or all registered universities."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Sequence

from alembic import command
from alembic.config import Config

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.ingestion.contracts.normalized import CanonicalSnapshot
from andromeda.ingestion.contracts.raw import RawTracerBundle
from andromeda.ingestion.capabilities import preflight
from andromeda.ingestion.quality import evaluate_quality
from andromeda.ingestion.registry import adapter_spec, create_adapter, supported_universities
from andromeda.composition import build_container
from andromeda.infrastructure.config import Settings, redact_database_url
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.shared.contracts.errors import ContractError, ErrorCode


logger = logging.getLogger("andromeda.runner")


@dataclass(frozen=True, slots=True)
class AndromedaRunResult:
    university: str
    run_id: str
    program_ids: tuple[str, ...]
    direction_count: int
    study_plan_count: int
    curriculum_item_count: int
    unique_discipline_count: int
    source_count: int
    source_gap_count: int


def _migrate(database_url: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def _validate(raw: RawTracerBundle, canonical: CanonicalSnapshot) -> None:
    if len({item.id for item in canonical.programs}) != len(canonical.programs):
        raise ValueError("canonical program IDs are not unique")
    directions = canonical.directions or (canonical.direction,)
    if len({item.id for item in directions}) != len(directions):
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


def run_university(
    *,
    university: str,
    mode: str,
    fixture_dir: Path | None,
    database_url: str,
    program_codes: Sequence[str] | None,
    minimum_ratio: float = 0.25,
) -> AndromedaRunResult:
    spec = adapter_spec(university)
    selected_fixture = fixture_dir or spec.default_fixture_dir
    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        Path(database_url.removeprefix("sqlite:///" )).parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        "ingestion_start university=%s mode=%s fixture=%s database=%s",
        spec.slug,
        mode,
        selected_fixture,
        redact_database_url(database_url),
    )
    preflight(spec.slug)
    settings = Settings.from_environment(database_url)
    engine = create_engine_for_url(database_url, **settings.engine_options)
    container = build_container(engine, settings)
    try:
        _migrate(database_url)
        repository = container.ingestion
        run_id = repository.start_run(
            source_profile=f"{spec.slug}:{mode}:cli:mvp023.v1",
            source_revision="fixture-manifest-v1" if mode == "fixture" else "official-live-v1",
            configuration_version="mvp023.v1",
            university_id=f"university:{spec.slug}",
        )
        try:
            adapter = create_adapter(spec.slug)
            try:
                captured = adapter.capture(mode=mode, fixture_dir=selected_fixture)
                repository.record_captured_metadata(run_id, captured)
                raw, canonical = adapter.parse(captured, program_codes=program_codes or None)
            finally:
                close = getattr(adapter, "close", None)
                if close is not None:
                    close()
            _validate(raw, canonical)
            repository.record_source_metadata(run_id, raw)
            previous = repository.previous_projection(str(canonical.university.id))
            quality = evaluate_quality(
                raw,
                canonical,
                previous=previous,
                minimum_relative_count=minimum_ratio,
                run_id=run_id,
            )
            repository.record_quality(
                run_id,
                quality,
                university_id=str(canonical.university.id),
                program_ids=tuple(str(program.id) for program in canonical.programs),
            )
            logger.info(
                "ingestion_quality_decision run_id=%s university=%s status=%s blocking=%d degradable=%d",
                run_id,
                spec.slug,
                quality.status,
                len(quality.blocking_reasons),
                len(quality.degradable_reasons),
            )
            if not quality.accepted:
                raise ContractError(
                    ErrorCode.CONTRACT_ERROR,
                    "INGESTION_QUALITY_REJECTED: " + ",".join(quality.blocking_reasons),
                )
            repository.ingest(raw, canonical, run_id=run_id)
        except Exception as exc:
            repository.mark_failed(run_id, exc)
            raise
        result = AndromedaRunResult(
            university=spec.slug,
            run_id=run_id,
            program_ids=tuple(program.id for program in canonical.programs),
            direction_count=len(canonical.directions or (canonical.direction,)),
            study_plan_count=len(canonical.curricula),
            curriculum_item_count=sum(len(item.items) for item in canonical.curricula),
            unique_discipline_count=len(canonical.disciplines),
            source_count=len(canonical.sources),
            source_gap_count=len(canonical.source_gaps),
        )
        logger.info(
            "ingestion_complete university=%s run_id=%s directions=%d programs=%d plans=%d disciplines=%d gaps=%d",
            result.university,
            result.run_id,
            result.direction_count,
            len(result.program_ids),
            result.study_plan_count,
            result.unique_discipline_count,
            result.source_gap_count,
        )
        return result
    finally:
        engine.dispose()


def _program_codes(values: Sequence[str] | None) -> tuple[str, ...]:
    result: list[str] = []
    for value in values or ():
        parts = value.split(":")
        result.append(parts[-1] if parts[0] == "program" else value)
    return tuple(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest source-backed university data into Andromeda canonical DB")
    parser.add_argument("--university", choices=(*supported_universities(), "all"), default="bmstu")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--database-url")
    parser.add_argument("--program-code", action="append", dest="program_codes")
    parser.add_argument("--program-id", action="append", dest="program_ids")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    parser.add_argument("--min-relative-count", type=float, default=None, help="Reject live runs below this fraction of the previous successful snapshot")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(name)s %(message)s")
    if args.program_codes and args.program_ids:
        raise SystemExit("use --program-code or --program-id, not both")
    settings = Settings.from_environment(args.database_url)
    database_url = settings.database_url
    requested_codes = _program_codes(args.program_codes or args.program_ids)
    universities = supported_universities() if args.university == "all" else (args.university,)
    results = [
        run_university(
            university=university,
            mode=args.mode,
            fixture_dir=args.fixture_dir,
            database_url=database_url,
            program_codes=requested_codes,
            minimum_ratio=settings.ingestion_min_relative_count if args.min_relative_count is None else args.min_relative_count,
        )
        for university in universities
    ]
    print(json.dumps({"results": [asdict(result) for result in results], "databaseTarget": redact_database_url(database_url)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
