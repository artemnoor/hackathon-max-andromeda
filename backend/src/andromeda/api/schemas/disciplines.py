from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import Discipline, DisciplineAreaCode, area_definition

from .common import DisciplineAreaResponse, DisciplineAreaSummaryResponse, DisciplineResponse


def discipline_response(discipline: Discipline) -> DisciplineResponse:
    return DisciplineResponse(
        id=discipline.id,
        name=discipline.name,
        normalized_name=discipline.normalized_name,
        area_weights=tuple(
            DisciplineAreaResponse(
                code=area_weight.area,
                name=area_definition(area_weight.area).name,
                description=area_definition(area_weight.area).description,
                weight=area_weight.weight,
            )
            for area_weight in discipline.area_weights
        ),
        primary_area=discipline.primary_area,
    )


def area_summary_response(area: DisciplineAreaCode, share: Decimal) -> DisciplineAreaSummaryResponse:
    return DisciplineAreaSummaryResponse(area=area, name=area_definition(area).name, share=share)


__all__ = [
    "area_summary_response",
    "discipline_response",
]
