from decimal import Decimal

from andromeda.modules.analytics.contracts.metrics import MetricAggregation, MetricEntityType
from andromeda.modules.analytics.contracts.public import (
    ActivitySignalCode,
    ProgramProjection,
    ProjectionDataQuality,
    ProjectionDataQualityStatus,
    ProjectionMetric,
    WorkloadSummary,
)
from andromeda.modules.analytics.contracts.query import QueryScope, QuerySpec
from andromeda.modules.analytics.domain.basis import MetricBasis
from andromeda.modules.analytics.services.cache import AnalyticsResultCache
from andromeda.modules.analytics.services.executor import AnalyticsExecutor
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode


def _projection(
    *,
    program_id: str,
    university_id: str,
    direction_id: str,
    mathematics: str,
    programming: str,
    physics: str,
) -> ProgramProjection:
    values = {
        code: ProjectionMetric(
            code=code,
            value=Decimal(value),
            coverage=Decimal("1"),
            confidence=Decimal("0.9"),
            status=ProjectionDataQualityStatus.AVAILABLE,
        )
        for code, value in {
            "mathematics": mathematics,
            "programming": programming,
            "physics": physics,
        }.items()
    }
    return ProgramProjection(
        program_id=program_id,
        university_id=university_id,
        direction_id=direction_id,
        program_code="09.03.03-01",
        program_name="Прикладная информатика",
        workload=WorkloadSummary(
            total_hours=100,
            total_credits=Decimal("10"),
            total_workload=Decimal("100"),
            basis=MetricBasis.HOURS,
        ),
        academic_areas={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")},
        semantic_features=values,
        activity_signals={ActivitySignalCode.SOFTWARE_CREATION: Decimal("1")},
        quality=ProjectionDataQuality(
            status=ProjectionDataQualityStatus.AVAILABLE,
            coverage=Decimal("1"),
            confidence=Decimal("0.9"),
            semantic_version="semantic-taxonomy.v1",
            classifier_version="semantic-classifier.v1",
        ),
    )


class _Reader:
    def __init__(self, projections: tuple[ProgramProjection, ...]) -> None:
        self.projections = projections
        self.query_calls = 0

    def query(self, spec, *, registry):  # type: ignore[no-untyped-def]
        del spec, registry
        self.query_calls += 1
        return self.projections

    def evidence(self, program_ids, *, metric_codes, schema_version):  # type: ignore[no-untyped-def]
        del program_ids, metric_codes, schema_version
        return ()


def test_mean_math_is_grouped_over_all_comparable_programs() -> None:
    reader = _Reader(
        (
            _projection(
                program_id="program:bmstu:09.03.03-01",
                university_id="university:bmstu",
                direction_id="direction:bmstu:09.03.03",
                mathematics="0.60",
                programming="0.80",
                physics="0.10",
            ),
            _projection(
                program_id="program:bmstu:09.03.03-02",
                university_id="university:bmstu",
                direction_id="direction:bmstu:09.03.03",
                mathematics="0.80",
                programming="0.70",
                physics="0.20",
            ),
            _projection(
                program_id="program:hse:09.03.03-01",
                university_id="university:hse",
                direction_id="direction:hse:09.03.03",
                mathematics="0.40",
                programming="0.60",
                physics="0.30",
            ),
            _projection(
                program_id="program:hse:09.03.03-02",
                university_id="university:hse",
                direction_id="direction:hse:09.03.03",
                mathematics="0.50",
                programming="0.50",
                physics="0.40",
            ),
        )
    )
    spec = QuerySpec(
        entity=MetricEntityType.PROGRAM,
        metrics=("math_share",),
        scope=QueryScope.ALL,
        aggregation=MetricAggregation.MEAN,
        group_by=(MetricEntityType.UNIVERSITY,),
        limit=10,
    )
    executor = AnalyticsExecutor(reader, cache=AnalyticsResultCache())

    result = executor.execute(spec)

    values = {row.entity_id: row.metrics["math_share"].value for row in result.rows}
    assert values == {"university:bmstu": Decimal("0.7"), "university:hse": Decimal("0.45")}
    assert {row.population_size for row in result.rows} == {2}
    assert result.population_size == 4


def test_repeated_materialized_query_uses_bounded_cache() -> None:
    reader = _Reader(
        (
            _projection(
                program_id="program:bmstu:09.03.03-01",
                university_id="university:bmstu",
                direction_id="direction:bmstu:09.03.03",
                mathematics="0.60",
                programming="0.80",
                physics="0.10",
            ),
        )
    )
    spec = QuerySpec(entity=MetricEntityType.PROGRAM, metrics=("math_share",))
    executor = AnalyticsExecutor(reader, cache=AnalyticsResultCache())

    executor.execute(spec)
    executor.execute(spec)

    assert reader.query_calls == 1
