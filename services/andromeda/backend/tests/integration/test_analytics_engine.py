from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.repositories.analytics import (
    SqlAlchemyProgramProjectionRepository,
)
from andromeda.modules.analytics.contracts.metrics import (
    MetricAggregation,
    MetricEntityType,
)
from andromeda.modules.analytics.contracts.query import (
    FilterKind,
    FilterOperator,
    QueryFilter,
    QueryScope,
    QuerySort,
    QuerySpec,
)
from andromeda.modules.analytics.services.executor import AnalyticsExecutor

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from run_andromeda_bmstu import run_ingest  # noqa: E402, I001


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
PROGRAM_A = "program:bmstu:09.03.01-02"
PROGRAM_B = "program:bmstu:09.03.01-12"


def _ingested_engine(tmp_path: Path):
    database_url = f"sqlite:///{(tmp_path / 'analytics-engine.db').as_posix()}"
    run_ingest(mode="fixture", fixture_dir=FIXTURE_DIR, database_url=database_url, program_codes=())
    return database_url, create_engine_for_url(database_url)


def test_typed_query_reads_persisted_program_metrics_and_evidence(tmp_path: Path) -> None:
    database_url, engine = _ingested_engine(tmp_path)
    try:
        reader = SqlAlchemyProgramProjectionRepository(engine)
        result = AnalyticsExecutor(reader).execute(
            QuerySpec(
                entity=MetricEntityType.PROGRAM,
                metrics=("math_share", "programming_share"),
                scope=QueryScope.PROGRAM,
                scope_ids=(PROGRAM_A, PROGRAM_B),
                sort=QuerySort(metric_code="math_share", descending=True),
                limit=2,
            )
        )
        assert result.status.value == "available"
        assert len(result.rows) == 2
        assert all(row.metrics["math_share"].value is not None for row in result.rows)
        assert all(row.evidence for row in result.rows)
        assert result.semantic_versions == ("semantic-taxonomy.v1",)
        assert result.projection_schema_version == "analytics-projection.v1"
    finally:
        engine.dispose()


def test_typed_query_groups_programs_by_university_after_direction_filter(tmp_path: Path) -> None:
    database_url, engine = _ingested_engine(tmp_path)
    try:
        result = AnalyticsExecutor(SqlAlchemyProgramProjectionRepository(engine)).execute(
            QuerySpec(
                entity=MetricEntityType.PROGRAM,
                metrics=("math_share",),
                filters=(
                    QueryFilter(
                        kind=FilterKind.DIRECTION,
                        ids=("direction:bmstu:09.03.01",),
                    ),
                ),
                group_by=(MetricEntityType.UNIVERSITY,),
                aggregation=MetricAggregation.MEAN,
                sort=QuerySort(metric_code="math_share"),
            )
        )
        assert len(result.rows) == 1
        assert result.rows[0].entity_id == "university:bmstu"
        assert result.rows[0].program_ids == (PROGRAM_A, PROGRAM_B)
        assert result.rows[0].metrics["math_share"].value is not None
    finally:
        engine.dispose()


def test_metric_threshold_preserves_missing_data_semantics(tmp_path: Path) -> None:
    database_url, engine = _ingested_engine(tmp_path)
    try:
        result = AnalyticsExecutor(SqlAlchemyProgramProjectionRepository(engine)).execute(
            QuerySpec(
                entity=MetricEntityType.PROGRAM,
                metrics=("math_share",),
                filters=(
                    QueryFilter(
                        kind=FilterKind.METRIC_THRESHOLD,
                        metric_code="math_share",
                        operator=FilterOperator.GTE,
                        threshold=Decimal("0"),
                    ),
                ),
                limit=10,
            )
        )
        assert len(result.rows) <= 10
        assert all(row.metrics["math_share"].value is not None for row in result.rows)
    finally:
        engine.dispose()
