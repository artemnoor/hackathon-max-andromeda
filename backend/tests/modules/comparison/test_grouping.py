from __future__ import annotations

from decimal import Decimal

from andromeda.modules.comparison.domain.entities import Workload
from andromeda.modules.comparison.services.aggregation import totals


def test_aggregation_returns_decimal_totals_without_curriculum_categories() -> None:
    workload = Workload(hours=12, credits=Decimal("1.50"))

    result = totals((workload,))

    assert result.hours == 12
    assert result.credits == Decimal("1.50")
