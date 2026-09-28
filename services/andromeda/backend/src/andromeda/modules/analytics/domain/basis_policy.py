"""Policy for selecting a comparable workload basis per metric."""

from __future__ import annotations

from decimal import Decimal

from ..contracts.metrics import MetricDefinition
from ..contracts.public import ProjectionDataQualityStatus
from ..contracts.quality import BasisSelection
from .basis import MetricBasis


def select_metric_basis(
    definition: MetricDefinition,
    *,
    coverage_by_basis: dict[MetricBasis, Decimal],
) -> BasisSelection:
    candidates = () if definition.preferred_basis is None else (definition.preferred_basis, *definition.fallback_basis)
    for basis in candidates:
        coverage = coverage_by_basis.get(basis, Decimal("0"))
        if basis is MetricBasis.COURSE_COUNT and coverage > Decimal("0"):
            return BasisSelection(
                basis=basis,
                coverage=min(Decimal("1"), coverage),
                status=ProjectionDataQualityStatus.AVAILABLE,
                reason="course-count basis is directly comparable",
            )
        if coverage >= definition.minimum_coverage:
            status = ProjectionDataQualityStatus.AVAILABLE if coverage == Decimal("1") else ProjectionDataQualityStatus.PARTIAL
            return BasisSelection(
                basis=basis,
                coverage=min(Decimal("1"), coverage),
                status=status,
                reason=f"selected {basis.value} at configured coverage threshold",
            )
    return BasisSelection(
        basis=None,
        coverage=max(coverage_by_basis.values(), default=Decimal("0")),
        status=ProjectionDataQualityStatus.INSUFFICIENT_DATA,
        reason="no preferred or fallback basis meets the comparability threshold",
    )


__all__ = ["select_metric_basis"]
