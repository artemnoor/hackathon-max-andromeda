"""Pure invariants shared by analytical projection builders and contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, TypeVar

DistributionKey = TypeVar("DistributionKey")


def distribution_is_complete(values: Mapping[DistributionKey, Decimal], *, tolerance: Decimal = Decimal("0.001")) -> bool:
    """Return whether a non-empty distribution accounts for the whole workload."""

    return bool(values) and abs(sum(values.values(), Decimal("0")) - Decimal("1")) <= tolerance


def quality_status_for(*, coverage: Decimal, confidence: Decimal, has_value: bool) -> str:
    """Choose a stable quality label without converting missing data to zero."""

    if not has_value:
        return "unavailable"
    if coverage <= Decimal("0"):
        return "insufficient_data"
    if coverage < Decimal("1") or confidence < Decimal("0.7"):
        return "partial"
    return "available"


__all__ = ["distribution_is_complete", "quality_status_for"]
