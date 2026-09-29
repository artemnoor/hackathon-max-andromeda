"""Application facade for the versioned metric registry."""

from ..contracts.metrics import MetricAggregation, MetricDefinition, MetricEntityType
from ..domain.metric_registry import MetricRegistry


class MetricRegistryService:
    def __init__(self, registry: MetricRegistry | None = None) -> None:
        self._registry = registry or MetricRegistry()

    @property
    def version(self) -> str:
        return self._registry.version

    def resolve(self, code: str, *, entity_type: MetricEntityType | None = None, aggregation: MetricAggregation | None = None) -> MetricDefinition:
        return self._registry.get(code, entity_type=entity_type, aggregation=aggregation)

    def list(self) -> tuple[MetricDefinition, ...]:
        return self._registry.all()


__all__ = ["MetricRegistryService"]
