"""Profile one fixed, source-backed analytics query.

The script is an operational benchmark, not a second query language.  It
constructs one allow-listed ``QuerySpec`` and reports bounded counts/timing;
the actual SQL remains owned by ``AnalyticsExecutor`` and its repository.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
from time import perf_counter
from typing import Sequence

from sqlalchemy import event

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.infrastructure.config import redact_database_url  # noqa: E402
from andromeda.infrastructure.database import create_engine_for_url  # noqa: E402
from andromeda.infrastructure.repositories.analytics import (  # noqa: E402
    SqlAlchemyProgramProjectionRepository,
)
from andromeda.modules.analytics.contracts.metrics import (  # noqa: E402
    MetricAggregation,
    MetricEntityType,
)
from andromeda.modules.analytics.contracts.query import QuerySort, QuerySpec  # noqa: E402
from andromeda.modules.analytics.services.executor import AnalyticsExecutor  # noqa: E402
from andromeda.shared.contracts.versions import (  # noqa: E402
    ANALYTICS_PROJECTION_SCHEMA_VERSION,
    METRIC_REGISTRY_VERSION,
)

logger = logging.getLogger("andromeda.scripts.profile_analytics")


def benchmark(database_url: str, *, limit: int = 20) -> dict[str, object]:
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    engine = create_engine_for_url(database_url, pool_size=2, max_overflow=0)
    select_count = 0

    def count_selects(*_: object) -> None:
        nonlocal select_count
        statement = str(_[2]) if len(_) > 2 else ""
        if not statement.lstrip().upper().startswith("SELECT"):
            return
        select_count += 1

    event.listen(engine, "before_cursor_execute", count_selects)
    spec = QuerySpec(
        entity=MetricEntityType.PROGRAM,
        metrics=("math_share",),
        aggregation=MetricAggregation.MEAN,
        group_by=(MetricEntityType.UNIVERSITY,),
        sort=QuerySort(metric_code="math_share", descending=True),
        limit=limit,
    )
    started = perf_counter()
    try:
        result = AnalyticsExecutor(
            SqlAlchemyProgramProjectionRepository(engine),
        ).execute(spec)
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)
        engine.dispose()
    elapsed_ms = (perf_counter() - started) * 1000
    logger.info(
        "analytics_benchmark_complete query=mean_math_by_university select_count=%d rows=%d population=%d duration_ms=%.3f",
        select_count,
        len(result.rows),
        result.population_size,
        elapsed_ms,
    )
    return {
        "benchmark": "mean_math_by_university.v1",
        "databaseTarget": redact_database_url(database_url),
        "metricRegistryVersion": METRIC_REGISTRY_VERSION,
        "projectionSchemaVersion": ANALYTICS_PROJECTION_SCHEMA_VERSION,
        "query": spec.model_dump(mode="json"),
        "selectCount": select_count,
        "rowCount": len(result.rows),
        "populationSize": result.population_size,
        "status": result.status.value,
        "coverage": str(result.coverage),
        "durationMs": round(elapsed_ms, 3),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile one bounded typed analytics query")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = args.database_url or os.environ.get("ANDROMEDA_POSTGRES_TEST_URL") or os.environ.get("ANDROMEDA_DATABASE_URL")
    if not database_url:
        raise SystemExit("set --database-url or ANDROMEDA_POSTGRES_TEST_URL")
    artifact = benchmark(database_url, limit=args.limit)
    payload = json.dumps(artifact, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(args.out)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
