from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.campus.contracts.public import CampusEventFilters, CampusPointFilters
from andromeda.modules.campus.domain.entities import CampusPoint, CampusPointType
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import SourceAttribution


def _provenance() -> tuple[SourceAttribution, ...]:
    return (
        SourceAttribution(
            kind=SourceKind.BMSTU_EVENTS,
            url="https://bmstu.ru/events",
            captured_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
            content_sha256="a" * 64,
            locator="events[0]",
        ),
    )


def _point(**overrides: object) -> CampusPoint:
    values: dict[str, object] = {
        "id": "venue:bmstu:main-campus",
        "point_type": CampusPointType.BUILDING,
        "name": "Главный корпус",
        "address": "Москва, 2-я Бауманская улица, 5",
        "latitude": Decimal("55.7666"),
        "longitude": Decimal("37.6855"),
        "university_ids": ("university:bmstu",),
        "department_ids": ("department:bmstu:iu7",),
        "program_ids": ("program:09.03.01-02",),
        "event_count": 1,
        "provenance": _provenance(),
    }
    values.update(overrides)
    return CampusPoint(**values)


def test_campus_point_reuses_venue_identity_and_validates_coordinates() -> None:
    point = _point()
    assert point.id == "venue:bmstu:main-campus"
    assert point.point_type is CampusPointType.BUILDING

    with pytest.raises(ValidationError, match="provided together"):
        _point(longitude=None)


def test_campus_point_rejects_duplicate_links_and_wrong_university_prefix() -> None:
    with pytest.raises(ValidationError, match="unique canonical IDs"):
        _point(program_ids=("program:09.03.01-02", "program:09.03.01-02"))
    with pytest.raises(ValidationError, match="belong to one"):
        _point(id="venue:other:main-campus")


def test_campus_filters_are_strict_bounded_and_timezone_aware() -> None:
    filters = CampusPointFilters(program_id="program:09.03.01-02", limit=10)
    assert filters.limit == 10

    with pytest.raises(ValidationError):
        CampusPointFilters(limit=101)
    with pytest.raises(ValidationError, match="timezone-aware"):
        CampusEventFilters(from_date=datetime(2026, 10, 1))
    with pytest.raises(ValidationError, match="recommended filtering"):
        CampusEventFilters(recommended=True)
