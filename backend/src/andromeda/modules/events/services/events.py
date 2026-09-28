from __future__ import annotations

import logging

from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.ids import EventId

from ..contracts.public import EventFilters
from ..contracts.results import EventDetailResult, EventListResult
from ..repository.ports import EventReader


logger = logging.getLogger("andromeda.events")


class EventService:
    """Query use case for source-backed university events."""

    def __init__(self, events: EventReader) -> None:
        self._events = events

    def list(self, filters: EventFilters) -> EventListResult:
        logger.debug(
            "events_use_case_start recommended=%s program_filter=%s limit=%d",
            filters.recommended,
            filters.program_id,
            filters.limit,
        )
        result = self._events.list(filters)
        logger.info("events_use_case_complete result_count=%d total=%d recommended=%s", len(result.items), result.total, filters.recommended)
        return result

    def get(self, event_id: EventId) -> EventDetailResult:
        logger.debug("events_detail_use_case_start event_id=%s", event_id)
        event = self._events.get(event_id)
        if event is None:
            logger.warning("events_detail_not_found event_id=%s", event_id)
            raise NotFoundError("Event was not found")
        logger.info("events_detail_use_case_complete event_id=%s", event_id)
        return EventDetailResult(event=event)


__all__ = ["EventService"]
