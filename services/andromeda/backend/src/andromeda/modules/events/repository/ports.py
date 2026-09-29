"""Storage ports for the events module."""

from __future__ import annotations

from typing import Protocol

from andromeda.shared.contracts.ids import EventId

from ..contracts.public import EventFilters
from ..contracts.results import EventListResult
from ..domain.entities import Event


class EventReader(Protocol):
    def list(self, filters: EventFilters) -> EventListResult: ...

    def get(self, event_id: EventId) -> Event | None: ...


class EventRepository(EventReader, Protocol):
    """Combined read/write boundary reserved for the persistence adapter."""


__all__ = ["EventReader", "EventRepository"]
