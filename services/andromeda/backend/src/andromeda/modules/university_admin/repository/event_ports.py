from __future__ import annotations

from datetime import datetime
from typing import Protocol

from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.shared.contracts.ids import UniversityEventId, UniversityId

from ..contracts.events import AgendaItem, EditorialEvent, EditorialEventRelations, EditorialEventSnapshot, EditorialEventStatus


class UniversityEditorialEventReader(Protocol):
    def get_event(self, event_id: UniversityEventId) -> EditorialEvent | None: ...

    def get_relations(self, event_id: UniversityEventId) -> EditorialEventRelations: ...

    def list_agenda(self, event_id: UniversityEventId) -> tuple[AgendaItem, ...]: ...

    def list_events(
        self,
        university_id: UniversityId,
        *,
        status: EditorialEventStatus | None = None,
        kind: EventKind | None = None,
        format: EventFormat | None = None,
        public_only: bool = False,
    ) -> tuple[EditorialEvent, ...]: ...

    def list_snapshots(
        self,
        university_id: UniversityId,
        *,
        status: EditorialEventStatus | None = None,
        kind: EventKind | None = None,
        format: EventFormat | None = None,
        public_only: bool = False,
    ) -> tuple[EditorialEventSnapshot, ...]: ...

    def venue_belongs(self, university_id: UniversityId, venue_id: str) -> bool: ...


class UniversityEditorialEventWriter(Protocol):
    def create_event(self, event: EditorialEvent, relations: EditorialEventRelations, agenda: tuple[AgendaItem, ...]) -> EditorialEvent: ...

    def update_event(self, event: EditorialEvent, relations: EditorialEventRelations, agenda: tuple[AgendaItem, ...], *, expected_revision: int) -> EditorialEvent: ...


__all__ = ["UniversityEditorialEventReader", "UniversityEditorialEventWriter"]
