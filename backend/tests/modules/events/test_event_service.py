from __future__ import annotations

from datetime import datetime, timezone

import pytest

from andromeda.modules.events.contracts.public import Event, EventFilters, EventFormat, EventKind
from andromeda.modules.events.contracts.results import EventListResult
from andromeda.modules.events.services.events import EventService
from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.enums import SourceKind


def _event() -> Event:
    return Event(
        id="event:bmstu:sample",
        title="Sample",
        kind=EventKind.LECTURE,
        format=EventFormat.ONLINE,
        starts_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        university_ids=("university:bmstu",),
        provenance=(
            {
                "kind": SourceKind.BMSTU_EVENTS,
                "url": "https://bmstu.ru/events",
                "captured_at": datetime(2026, 9, 12, tzinfo=timezone.utc),
                "content_sha256": "b" * 64,
            },
        ),
    )


class _Reader:
    def __init__(self, event: Event) -> None:
        self.event = event
        self.filters: EventFilters | None = None

    def list(self, filters: EventFilters) -> EventListResult:
        self.filters = filters
        return EventListResult(items=(self.event,), total=1)

    def get(self, event_id: str) -> Event | None:
        return self.event if event_id == self.event.id else None


def test_event_service_passes_immutable_recommendation_filters_to_reader() -> None:
    reader = _Reader(_event())
    result = EventService(reader).list(
        EventFilters(recommended=True, recommended_program_ids=("program:09.03.01-02",))
    )
    assert result.total == 1
    assert reader.filters is not None
    assert reader.filters.recommended_program_ids == ("program:09.03.01-02",)


def test_event_service_raises_public_not_found_error() -> None:
    with pytest.raises(NotFoundError):
        EventService(_Reader(_event())).get("event:bmstu:missing")
