from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.events.contracts.public import Event, EventFilters, EventFormat, EventKind
from andromeda.shared.contracts.enums import SourceKind


def _event(**overrides: object) -> Event:
    values: dict[str, object] = {
        "id": "event:bmstu:open-day-2026",
        "title": "День открытых дверей",
        "kind": EventKind.OPEN_DAY,
        "format": EventFormat.OFFLINE,
        "starts_at": datetime(2026, 10, 10, 10, tzinfo=timezone.utc),
        "university_ids": ("university:bmstu",),
        "program_ids": ("program:09.03.01-02",),
        "provenance": (
            {
                "kind": SourceKind.BMSTU_EVENTS,
                "url": "https://events.example.test/bmstu",
                "captured_at": datetime(2026, 9, 12, tzinfo=timezone.utc),
                "content_sha256": "a" * 64,
            },
        ),
    }
    values.update(overrides)
    return Event.model_validate(values)


def test_event_and_venue_accept_canonical_links_and_coordinates() -> None:
    event = _event(
        venue={
            "id": "venue:bmstu:main-campus",
            "name": "Главный корпус",
            "address": "Москва",
            "latitude": Decimal("55.7666"),
            "longitude": Decimal("37.6855"),
        }
    )
    assert event.id == "event:bmstu:open-day-2026"
    assert event.venue is not None
    assert event.venue.latitude == Decimal("55.7666")


@pytest.mark.parametrize(
    "overrides",
    [
        {"starts_at": datetime(2026, 10, 10, 10)},
        {"ends_at": datetime(2026, 10, 10, 9, tzinfo=timezone.utc)},
        {"university_ids": ("university:bmstu", "university:bmstu")},
        {"venue": {"id": "venue:bmstu:main-campus", "name": "Главный корпус", "latitude": Decimal("55.7")}},
        {"id": "event:BMSTU:bad"},
    ],
)
def test_event_rejects_invalid_invariants(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _event(**overrides)


def test_recommended_filter_requires_program_evidence() -> None:
    with pytest.raises(ValidationError, match="recommended filtering"):
        EventFilters(recommended=True)
    filters = EventFilters(recommended=True, recommended_program_ids=("program:09.03.01-02",))
    assert filters.recommended is True


def test_date_window_must_be_aware_and_ordered() -> None:
    with pytest.raises(ValidationError):
        EventFilters(from_date=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        EventFilters(
            from_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
            to_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
