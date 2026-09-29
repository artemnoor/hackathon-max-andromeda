from __future__ import annotations

import sys
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
    QueryFilter,
    QuerySpec,
)
from andromeda.modules.analytics.services.executor import AnalyticsExecutor
from sqlalchemy import event

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from run_andromeda_bmstu import run_ingest  # noqa: E402, I001


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def test_grouped_analytics_uses_bounded_batch_reads_without_n_plus_one(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'analytics-budget.db').as_posix()}"
    run_ingest(mode="fixture", fixture_dir=FIXTURE_DIR, database_url=database_url, program_codes=())
    engine = create_engine_for_url(database_url)
    statements: list[str] = []
    def listener(_conn, _cursor, statement, *_args):
        statements.append(statement)

    try:
        event.listen(engine, "before_cursor_execute", listener)
        result = AnalyticsExecutor(SqlAlchemyProgramProjectionRepository(engine)).execute(
            QuerySpec(
                entity=MetricEntityType.PROGRAM,
                metrics=("math_share",),
                filters=(QueryFilter(kind=FilterKind.DIRECTION, ids=("direction:bmstu:09.03.01",)),),
                group_by=(MetricEntityType.UNIVERSITY,),
                aggregation=MetricAggregation.MEAN,
            )
        )
        assert result.rows
        select_statements = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
        assert len(select_statements) <= 3
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        engine.dispose()
