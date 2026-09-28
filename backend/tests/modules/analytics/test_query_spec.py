from decimal import Decimal

import pytest
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
from andromeda.modules.analytics.domain.query_validation import validate_query_spec
from andromeda.shared.contracts.errors import ContractError, ErrorCode
from pydantic import ValidationError


def test_query_spec_supports_grouped_program_metric_query() -> None:
    spec = QuerySpec(
        entity=MetricEntityType.PROGRAM,
        metrics=("math_share", "programming_share"),
        scope=QueryScope.ALL,
        filters=(
            QueryFilter(
                kind=FilterKind.METRIC_THRESHOLD,
                metric_code="physics_share",
                operator=FilterOperator.LT,
                threshold=Decimal("0.2"),
            ),
        ),
        group_by=(MetricEntityType.UNIVERSITY,),
        aggregation=MetricAggregation.MEAN,
        sort=QuerySort(metric_code="math_share"),
        limit=10,
    )

    assert validate_query_spec(spec).limit == 10


def test_query_spec_rejects_unsupported_metric_and_raw_sql_shaped_sort() -> None:
    unsupported = QuerySpec(entity=MetricEntityType.PROGRAM, metrics=("unicorn_quality",))
    with pytest.raises(ContractError) as error:
        validate_query_spec(unsupported)
    assert error.value.code is ErrorCode.UNSUPPORTED_METRIC

    with pytest.raises(ContractError):
        validate_query_spec(
            QuerySpec(
                entity=MetricEntityType.PROGRAM,
                metrics=("math_share",),
                sort=QuerySort(metric_code="value; DROP TABLE programs"),
            )
        )


def test_query_spec_bounds_and_canonical_ids_are_enforced() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(entity=MetricEntityType.PROGRAM, metrics=("math_share",) * 9)
    with pytest.raises(ContractError) as error:
        validate_query_spec(
            QuerySpec(
                entity=MetricEntityType.PROGRAM,
                metrics=("math_share",),
                scope=QueryScope.PROGRAM,
                scope_ids=("program:unresolved",),
            )
        )
    assert error.value.code is ErrorCode.INVALID_QUERY
