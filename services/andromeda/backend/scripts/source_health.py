"""Read-only live source probe; it never projects canonical data."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from andromeda.ingestion.quality import evaluate_quality  # noqa: E402
from andromeda.ingestion.capabilities import preflight  # noqa: E402
from andromeda.ingestion.registry import adapter_spec, create_adapter, supported_universities  # noqa: E402
from andromeda.infrastructure.config import Settings, redact_database_url  # noqa: E402
from andromeda.infrastructure.database import create_engine_for_url  # noqa: E402
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository  # noqa: E402


logger = logging.getLogger("andromeda.source_health")


@dataclass(frozen=True, slots=True)
class SourceHealthProbeResult:
    run_id: str
    university: str
    mode: str
    source_profile: str
    status: str
    source_hashes: tuple[str, ...] = ()
    source_gap_count: int = 0
    critical_gap_count: int = 0
    diagnostic_count: int = 0
    previous_good_run_id: str | None = None
    metrics: dict[str, Any] | None = None
    error_code: str | None = None


def probe_university(
    *,
    university: str,
    mode: str = "live",
    fixture_dir: Path | None = None,
    database_url: str | None = None,
    minimum_ratio: float = 0.25,
) -> SourceHealthProbeResult:
    spec = adapter_spec(university)
    probe_id = f"probe:{uuid4().hex}"
    source_profile = f"{spec.slug}:{mode}:probe:mvp023.v1"
    adapter = create_adapter(spec.slug)
    engine = None
    try:
        preflight(spec.slug)
        captured = adapter.capture(mode=mode, fixture_dir=fixture_dir or spec.default_fixture_dir if mode == "fixture" else fixture_dir)
        raw, canonical = adapter.parse(captured)
        previous = None
        if database_url is not None:
            engine = create_engine_for_url(database_url)
            previous = SqlAlchemyIngestionRepository(engine).previous_projection(str(canonical.university.id))
        outcome = evaluate_quality(raw, canonical, previous=previous, minimum_relative_count=minimum_ratio, run_id=probe_id)
        critical_gap_value = outcome.metrics.get("critical_gap_count", 0)
        critical_gap_count = int(critical_gap_value) if isinstance(critical_gap_value, (int, float, str)) else 0
        return SourceHealthProbeResult(
            run_id=probe_id,
            university=spec.slug,
            mode=mode,
            source_profile=source_profile,
            status=outcome.status,
            source_hashes=tuple(snapshot.content_sha256 for snapshot in raw.snapshots),
            source_gap_count=len(canonical.source_gaps),
            critical_gap_count=critical_gap_count,
            diagnostic_count=len(raw.diagnostics),
            previous_good_run_id=outcome.previous_good_run_id,
            metrics=dict(outcome.metrics),
            error_code="SOURCE_QUALITY_REJECTED" if not outcome.accepted else None,
        )
    except Exception as exc:
        logger.exception("source_health_probe_failed probe_id=%s university=%s", probe_id, spec.slug)
        return SourceHealthProbeResult(
            run_id=probe_id,
            university=spec.slug,
            mode=mode,
            source_profile=source_profile,
            status="failed",
            error_code=type(exc).__name__,
        )
    finally:
        close = getattr(adapter, "close", None)
        if close is not None:
            close()
        if engine is not None:
            engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe official university sources without mutating canonical data")
    parser.add_argument("--database-url")
    parser.add_argument("--mode", choices=("fixture", "live"), default="live")
    parser.add_argument("--university", choices=(*supported_universities(), "all"), default="all")
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--min-relative-count", type=float, default=None)
    parser.add_argument("--artifact", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings.from_environment(args.database_url)
    universities = supported_universities() if args.university == "all" else (args.university,)
    results = tuple(
        probe_university(
            university=university,
            mode=args.mode,
            fixture_dir=args.fixture_dir,
            database_url=settings.database_url,
            minimum_ratio=settings.ingestion_min_relative_count if args.min_relative_count is None else args.min_relative_count,
        )
        for university in universities
    )
    payload = {
        "databaseTarget": redact_database_url(settings.database_url),
        "mutatesCanonicalProjection": False,
        "results": [asdict(result) for result in results],
    }
    rendered = json.dumps(payload, default=str, ensure_ascii=False, indent=2)
    print(rendered)
    if args.artifact is not None:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(rendered + "\n", encoding="utf-8")
    return 1 if any(result.status in {"failed", "rejected"} for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
