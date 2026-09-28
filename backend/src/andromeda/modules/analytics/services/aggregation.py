"""Missing-data-aware aggregation over persisted projection metrics."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from statistics import median

from ..contracts.metrics import MetricAggregation
from ..contracts.public import ProjectionDataQualityStatus, ProjectionMetric


def aggregate_metrics(values: Iterable[ProjectionMetric], aggregation: MetricAggregation, *, weights: Iterable[Decimal] = ()) -> ProjectionMetric:
    all_values = tuple(values)
    observations = tuple(value for value in all_values if value.value is not None)
    if not observations:
        template = all_values[0] if all_values else None
        return ProjectionMetric(
            code=template.code if template else "unavailable",
            unit=template.unit if template else "unknown",
            status=ProjectionDataQualityStatus.INSUFFICIENT_DATA,
        )
    numbers = tuple(value.value for value in observations if value.value is not None)
    if aggregation is MetricAggregation.SUM:
        result = sum(numbers, Decimal("0"))
    elif aggregation is MetricAggregation.COUNT:
        result = Decimal(len(numbers))
    elif aggregation is MetricAggregation.MIN:
        result = min(numbers)
    elif aggregation is MetricAggregation.MAX:
        result = max(numbers)
    elif aggregation is MetricAggregation.MEDIAN:
        result = Decimal(str(median(numbers)))
    elif aggregation is MetricAggregation.WEIGHTED_MEAN:
        selected_weights = tuple(weights)
        usable = selected_weights[: len(observations)]
        denominator = sum(usable, Decimal("0"))
        result = sum((value * weight for value, weight in zip(numbers, usable, strict=False)), Decimal("0")) / denominator if denominator else sum(numbers, Decimal("0")) / Decimal(len(numbers))
    else:
        result = sum(numbers, Decimal("0")) / Decimal(len(numbers))
    coverage = sum((value.coverage for value in observations), Decimal("0")) / Decimal(len(observations))
    confidence = sum((value.confidence for value in observations), Decimal("0")) / Decimal(len(observations))
    status = ProjectionDataQualityStatus.AVAILABLE if len(observations) == len(all_values) and coverage == Decimal("1") else ProjectionDataQualityStatus.PARTIAL
    template = observations[0]
    return ProjectionMetric(
        code=template.code,
        value=result,
        unit=template.unit,
        basis=template.basis,
        coverage=coverage,
        confidence=confidence,
        status=status,
        provenance=template.provenance,
        source_gaps=template.source_gaps,
    )


__all__ = ["aggregate_metrics"]
