from __future__ import annotations

from decimal import Decimal

from andromeda.modules.comparison.domain.entities import Workload
from andromeda.modules.comparison.services.aggregation import totals


def test_totals_do_not_convert_decimal_credits_through_float() -> None:
    result = totals((Workload(hours=1, credits=Decimal("0.10")), Workload(hours=2, credits=Decimal("0.20"))))
    assert result.credits == Decimal("0.30")
