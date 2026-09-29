from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.modules.university_admin.contracts.catalog import CategoryKind, EditorialStatus, EditorialVisibility
from andromeda.modules.university_admin.contracts.events import AgendaItem, EditorialAudienceMode, EditorialEventRelations, EditorialEventSnapshot, EditorialEventStatus
from andromeda.modules.university_admin.services.events import UniversityEditorialEventService
from andromeda.shared.contracts.errors import ConflictError, ValidationError


ACCOUNT_ID = "account:" + "a" * 32
UNIVERSITY_ID = "university:bmstu"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
UNIT_ID = "unit:bmstu:iu"
PROGRAM_ID = "program:bmstu:09.03.01-01"
CATEGORY_ID = "category:bmstu:events"


class _Reader:
    def __init__(self) -> None:
        self.events = {}
        self.relations = {}
        self.agendas = {}
        self.units = {UNIT_ID: SimpleNamespace(unit_id=UNIT_ID, university_id=UNIVERSITY_ID, status=EditorialStatus.PUBLISHED, name="ИУ")}
        self.categories = {CATEGORY_ID: SimpleNamespace(category_id=CATEGORY_ID, university_id=UNIVERSITY_ID, category_kind=CategoryKind.EVENT, status=EditorialStatus.PUBLISHED, name="События")}

    def get_event(self, event_id):
        return self.events.get(event_id)

    def get_relations(self, event_id):
        return self.relations[event_id]

    def list_agenda(self, event_id):
        return self.agendas.get(event_id, ())

    def list_events(self, university_id, *, status=None, kind=None, format=None, public_only=False):
        return tuple(item for item in self.events.values() if item.university_id == university_id and (status is None or item.status is status) and (not public_only or item.status is EditorialEventStatus.PUBLISHED))

    def list_snapshots(self, university_id, *, status=None, kind=None, format=None, public_only=False):
        return tuple(
            EditorialEventSnapshot(event=event, relations=self.relations[event.event_id], agenda=self.agendas.get(event.event_id, ()))
            for event in self.list_events(university_id, status=status, kind=kind, format=format, public_only=public_only)
        )

    def venue_belongs(self, university_id, venue_id):
        return False


class _Writer:
    def __init__(self, reader: _Reader) -> None:
        self.reader = reader

    def create_event(self, event, relations, agenda):
        self.reader.events[event.event_id] = event
        self.reader.relations[event.event_id] = relations
        self.reader.agendas[event.event_id] = agenda
        return event

    def update_event(self, event, relations, agenda, *, expected_revision):
        current = self.reader.events[event.event_id]
        if current.revision != expected_revision:
            raise ConflictError("Event revision is stale")
        updated = event.model_copy(update={"revision": expected_revision + 1})
        self.reader.events[event.event_id] = updated
        self.reader.relations[event.event_id] = relations
        self.reader.agendas[event.event_id] = agenda
        return updated


class _Catalog:
    def __init__(self, reader: _Reader) -> None:
        self.reader = reader

    def list_units(self, university_id, *, include_archived=True):
        return tuple(item for item in self.reader.units.values() if include_archived or item.status is not EditorialStatus.ARCHIVED)

    def list_categories(self, university_id, *, include_archived=True):
        return tuple(item for item in self.reader.categories.values() if include_archived or item.status is not EditorialStatus.ARCHIVED)

    def list_program_editorials(self, university_id):
        return ()


class _Canonical:
    def list_programs(self, university_id):
        return (SimpleNamespace(id=PROGRAM_ID, name="Информатика"),)

    def list_disciplines(self, university_id):
        return ()

    def program_belongs(self, university_id, program_id):
        return university_id == UNIVERSITY_ID and program_id == PROGRAM_ID

    def discipline_belongs(self, university_id, discipline_id):
        return False


def _service() -> tuple[UniversityEditorialEventService, _Reader]:
    reader = _Reader()
    return UniversityEditorialEventService(reader, _Writer(reader), _Catalog(reader), _Canonical()), reader


def _create(service: UniversityEditorialEventService, *, audience=EditorialAudienceMode.ALL_UNIVERSITY, unit_ids=(), program_ids=(), category_ids=(CATEGORY_ID,)):
    return service.create_event(
        university_id=UNIVERSITY_ID,
        account_id=ACCOUNT_ID,
        slug="open-day",
        title="День открытых дверей",
        kind=EventKind.OPEN_DAY,
        format=EventFormat.HYBRID,
        starts_at=NOW + timedelta(days=1),
        ends_at=NOW + timedelta(days=1, hours=3),
        description="План мероприятия",
        registration_url=None,
        venue_id=None,
        location_label="Главный корпус",
        location_address=None,
        online_url=None,
        audience_mode=audience,
        unit_ids=unit_ids,
        program_ids=program_ids,
        category_ids=category_ids,
        agenda=(),
    )


def test_event_lifecycle_and_agenda_window() -> None:
    service, reader = _service()
    draft = _create(service)
    agenda = (
        AgendaItem(
            itemId="agenda:open-day:1",
            eventId=draft.event.event_id,
            position=1,
            title="Регистрация",
            startsAt=NOW + timedelta(days=1, minutes=5),
            endsAt=NOW + timedelta(days=1, minutes=20),
            revision=1,
        ),
    )
    with_agenda = service.replace_agenda(
        university_id=UNIVERSITY_ID,
        event_id=draft.event.event_id,
        account_id=ACCOUNT_ID,
        expected_revision=draft.event.revision,
        agenda=agenda,
    )
    published = service.publish_event(
        university_id=UNIVERSITY_ID,
        event_id=draft.event.event_id,
        account_id=ACCOUNT_ID,
        expected_revision=with_agenda.event.revision,
    )
    assert published.event.status is EditorialEventStatus.PUBLISHED
    assert published.agenda[0].title == "Регистрация"
    archived = service.archive_event(
        university_id=UNIVERSITY_ID,
        event_id=draft.event.event_id,
        account_id=ACCOUNT_ID,
        expected_revision=published.event.revision,
    )
    assert archived.event.status is EditorialEventStatus.ARCHIVED
    assert reader.events[draft.event.event_id].status is EditorialEventStatus.ARCHIVED


def test_event_audience_modes_and_target_lifecycle_are_explicit() -> None:
    service, reader = _service()
    with pytest.raises(ValidationError):
        _create(service, audience=EditorialAudienceMode.SELECTED_UNITS)
    selected = _create(service, audience=EditorialAudienceMode.SELECTED_UNITS, unit_ids=(UNIT_ID,), category_ids=())
    public = service.list_public_events(UNIVERSITY_ID)
    assert len(public) == 0
    reader.units[UNIT_ID].status = EditorialStatus.ARCHIVED
    assert service.list_public_events(UNIVERSITY_ID) == ()

    all_university = _create(service, audience=EditorialAudienceMode.UNAFFILIATED, category_ids=())
    assert all_university.event.audience_mode is EditorialAudienceMode.UNAFFILIATED


def test_event_rejects_naive_agenda_and_stale_revision() -> None:
    service, _ = _service()
    with pytest.raises(ValueError):
        AgendaItem(itemId="agenda:naive", eventId="university-event:bmstu:" + "a" * 32, position=1, title="Наивное время", startsAt=datetime(2026, 9, 21, 13, 0), revision=1)
    draft = _create(service, category_ids=())
    with pytest.raises(ConflictError):
        service.replace_agenda(
            university_id=UNIVERSITY_ID,
            event_id=draft.event.event_id,
            account_id=ACCOUNT_ID,
            expected_revision=999,
            agenda=(),
        )
