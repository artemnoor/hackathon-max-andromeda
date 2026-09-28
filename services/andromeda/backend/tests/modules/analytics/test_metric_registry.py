import pytest
from andromeda.modules.analytics.contracts.metrics import (
    MetricAggregation,
    MetricEntityType,
)
from andromeda.modules.analytics.services.metric_registry import MetricRegistryService
from andromeda.shared.contracts.errors import ContractError, ErrorCode


def test_registry_resolves_versioned_allow_listed_metric() -> None:
    registry = MetricRegistryService()

    definition = registry.resolve(
        "math_share",
        entity_type=MetricEntityType.PROGRAM,
        aggregation=MetricAggregation.MEAN,
    )

    assert definition.source_feature_code == "mathematics"
    assert registry.version == "metric-registry.v1"


def test_registry_rejects_unsupported_metric_before_repository_use() -> None:
    with pytest.raises(ContractError) as error:
        MetricRegistryService().resolve("unicorn_quality")

    assert error.value.code is ErrorCode.UNSUPPORTED_METRIC


def test_registry_rejects_entity_and_aggregation_mismatch() -> None:
    with pytest.raises(ContractError):
        MetricRegistryService().resolve("total_hours", entity_type=MetricEntityType.UNIVERSITY)
    with pytest.raises(ContractError):
        MetricRegistryService().resolve("math_share", aggregation=MetricAggregation.COUNT)
