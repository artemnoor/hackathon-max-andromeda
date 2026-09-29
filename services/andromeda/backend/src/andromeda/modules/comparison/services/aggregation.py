from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import Discipline, DisciplineAreaCode, DisciplineAreaSummary, area_position

from ..contracts.results import ComparisonTotals
from ..domain.entities import Workload


def totals(workloads: Iterable[Workload]) -> ComparisonTotals:
    values = tuple(workloads)
    return ComparisonTotals(
        hours=sum(value.hours for value in values),
        credits=sum((value.credits or Decimal("0") for value in values), Decimal("0")),
    )


def area_distribution(entries: Iterable[tuple[Workload, Discipline]]) -> tuple[DisciplineAreaSummary, ...]:
    values = tuple(entries)
    total_hours = sum(value.hours for value, _ in values)
    total_credits = sum((value.credits or Decimal("0") for value, _ in values), Decimal("0"))
    if total_hours > 0:
        basis = tuple((value, discipline, Decimal(value.hours)) for value, discipline in values)
        denominator = Decimal(total_hours)
    elif total_credits > 0:
        basis = tuple((value, discipline, value.credits or Decimal("0")) for value, discipline in values)
        denominator = total_credits
    else:
        return ()

    scores: dict[DisciplineAreaCode, Decimal] = defaultdict(lambda: Decimal("0"))
    for _, discipline, workload_basis in basis:
        for area_weight in discipline.area_weights:
            scores[area_weight.area] += workload_basis * area_weight.weight
    ordered = sorted(scores.items(), key=lambda entry: (-entry[1], area_position(entry[0])))
    shares = [
        DisciplineAreaSummary(area=area, share=(score / denominator).quantize(Decimal("0.0001")))
        for area, score in ordered
        if score > 0
    ]
    if shares:
        correction = Decimal("1.0000") - sum((item.share for item in shares), Decimal("0"))
        if correction:
            shares[0] = shares[0].model_copy(update={"share": shares[0].share + correction})
    return tuple(shares)
