"""Explicit workload basis selection for comparable analytical metrics."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum


class MetricBasis(StrEnum):
    HOURS = "hours"
    CREDITS = "credits"
    COURSE_COUNT = "course_count"
    NORMALIZED_WORKLOAD = "normalized_workload"


def select_workload_basis(
    *,
    total_hours: int | None,
    total_credits: Decimal | None,
    preferred: MetricBasis = MetricBasis.CREDITS,
) -> MetricBasis:
    """Select a basis without treating unavailable values as zero."""

    available = {
        MetricBasis.HOURS: total_hours is not None and total_hours > 0,
        MetricBasis.CREDITS: total_credits is not None and total_credits > 0,
    }
    if available.get(preferred, False):
        return preferred
    fallback = MetricBasis.HOURS if preferred is MetricBasis.CREDITS else MetricBasis.CREDITS
    if available[fallback]:
        return fallback
    return MetricBasis.NORMALIZED_WORKLOAD


__all__ = ["MetricBasis", "select_workload_basis"]
