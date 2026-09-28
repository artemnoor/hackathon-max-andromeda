from decimal import Decimal

from andromeda.modules.analytics.contracts.metrics import (
    MetricAggregation,
    MetricDefinition,
    MetricDomain,
    MetricEntityType,
)
from andromeda.modules.analytics.contracts.public import ProjectionDataQualityStatus
from andromeda.modules.analytics.domain.basis import MetricBasis
from andromeda.modules.analytics.domain.basis_policy import select_metric_basis


def _definition() -> MetricDefinition:
    return MetricDefinition(
        code="math_share",
        name="Math",
        description="Math share",
        unit="share",
        domain=MetricDomain.SEMANTIC,
        supported_entity_types=(MetricEntityType.PROGRAM,),
        allowed_aggregations=(MetricAggregation.VALUE,),
        preferred_basis=MetricBasis.CREDITS,
        fallback_basis=(MetricBasis.HOURS,),
        minimum_coverage=Decimal("0.8"),
    )


def test_basis_policy_prefers_credits_when_comparable() -> None:
    result = select_metric_basis(
        _definition(),
        coverage_by_basis={MetricBasis.CREDITS: Decimal("1"), MetricBasis.HOURS: Decimal("1")},
    )
    assert result.basis is MetricBasis.CREDITS
    assert result.status is ProjectionDataQualityStatus.AVAILABLE


def test_basis_policy_falls_back_to_hours_when_credits_are_partial() -> None:
    result = select_metric_basis(
        _definition(),
        coverage_by_basis={MetricBasis.CREDITS: Decimal("0.4"), MetricBasis.HOURS: Decimal("1")},
    )
    assert result.basis is MetricBasis.HOURS
    assert result.coverage == Decimal("1")


def test_basis_policy_never_turns_missing_workload_into_zero() -> None:
    result = select_metric_basis(_definition(), coverage_by_basis={})
    assert result.basis is None
    assert result.status is ProjectionDataQualityStatus.INSUFFICIENT_DATA
