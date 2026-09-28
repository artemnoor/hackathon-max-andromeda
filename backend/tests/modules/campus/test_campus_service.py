from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from andromeda.modules.campus.contracts.public import CampusEventFilters, CampusPointFilters
from andromeda.modules.campus.contracts.results import CampusPointDetailResult, CampusPointEventsResult, CampusPointListResult, CampusRecommendationResult
from andromeda.modules.campus.domain.entities import CampusPoint, CampusPointDetail, CampusPointType, CampusUniversityReference
from andromeda.modules.campus.services.campus import CampusService
from andromeda.modules.events.contracts.results import EventListResult
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.provenance import SourceAttribution


def _point() -> CampusPoint:
    return CampusPoint(
        id="venue:bmstu:main-campus",
        point_type=CampusPointType.BUILDING,
        name="Главный корпус",
        latitude=Decimal("55.7666"),
        longitude=Decimal("37.6855"),
        university_ids=("university:bmstu",),
        provenance=(
            SourceAttribution(
                kind=SourceKind.BMSTU_EVENTS,
                url="https://bmstu.ru/events",
                captured_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
                content_sha256="a" * 64,
            ),
        ),
    )


class FakeCampusReader:
    def __init__(self) -> None:
        self.point = _point()
        self.recommendation_ids: tuple[str, ...] | None = None

    def list(self, filters: CampusPointFilters) -> CampusPointListResult:
        del filters
        return CampusPointListResult(items=(self.point,), total=1)

    def get(self, point_id: str) -> CampusPointDetailResult | None:
        if point_id != self.point.id:
            return None
        detail = CampusPointDetail.model_validate(
            {
                **self.point.model_dump(),
                "universities": (CampusUniversityReference(
                    id="university:bmstu",
                    name="МГТУ им. Н.Э. Баумана",
                    city="Москва",
                    address="Москва, 2-я Бауманская улица, 5",
                    official_site="https://bmstu.ru",
                ),),
                "departments": (),
                "programs": (),
            }
        )
        return CampusPointDetailResult(point=detail)

    def events(self, point_id: str, filters: CampusEventFilters) -> CampusPointEventsResult:
        del filters
        return CampusPointEventsResult(point_id=point_id, events=EventListResult(items=(), total=0))

    def recommendations(self, program_ids: tuple[str, ...], *, limit: int) -> CampusRecommendationResult:
        self.recommendation_ids = program_ids
        del limit
        return CampusRecommendationResult(recommended_program_ids=program_ids)


def test_service_delegates_typed_reads_and_passes_only_program_ids() -> None:
    reader = FakeCampusReader()
    service = CampusService(reader)
    assert service.list(CampusPointFilters()).total == 1
    assert service.events("venue:bmstu:main-campus", CampusEventFilters()).total == 0
    result = service.recommendations(("program:09.03.01-02",))
    assert result.recommended_program_ids == ("program:09.03.01-02",)
    assert reader.recommendation_ids == ("program:09.03.01-02",)


def test_service_raises_stable_not_found_for_unknown_point() -> None:
    with pytest.raises(NotFoundError):
        CampusService(FakeCampusReader()).get("venue:bmstu:missing")
