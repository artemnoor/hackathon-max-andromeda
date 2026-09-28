from __future__ import annotations

from datetime import datetime, timezone
import logging

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    UniversityEditorialAgendaItemModel,
    UniversityEditorialEventCategoryLinkModel,
    UniversityEditorialEventModel,
    UniversityEditorialEventProgramLinkModel,
    UniversityEditorialEventUnitLinkModel,
    VenueUniversityLinkModel,
)
from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.modules.university_admin.contracts.events import AgendaItem, EditorialAudienceMode, EditorialEvent, EditorialEventRelations, EditorialEventSnapshot, EditorialEventStatus
from andromeda.modules.university_admin.repository.event_ports import UniversityEditorialEventReader, UniversityEditorialEventWriter
from andromeda.shared.contracts.errors import ConflictError
from andromeda.shared.contracts.ids import UniversityEventId, UniversityId


logger = logging.getLogger("andromeda.infrastructure.repositories.university_events")


class SqlAlchemyUniversityEditorialEventRepository(UniversityEditorialEventReader, UniversityEditorialEventWriter):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_event(self, event_id: UniversityEventId) -> EditorialEvent | None:
        model = self._session.get(UniversityEditorialEventModel, event_id)
        return _to_event(model) if model is not None else None

    def get_relations(self, event_id: UniversityEventId) -> EditorialEventRelations:
        units = self._session.scalars(
            select(UniversityEditorialEventUnitLinkModel.unit_id)
            .where(UniversityEditorialEventUnitLinkModel.event_id == event_id)
            .order_by(UniversityEditorialEventUnitLinkModel.unit_id)
        ).all()
        programs = self._session.scalars(
            select(UniversityEditorialEventProgramLinkModel.program_id)
            .where(UniversityEditorialEventProgramLinkModel.event_id == event_id)
            .order_by(UniversityEditorialEventProgramLinkModel.program_id)
        ).all()
        categories = self._session.scalars(
            select(UniversityEditorialEventCategoryLinkModel.category_id)
            .where(UniversityEditorialEventCategoryLinkModel.event_id == event_id)
            .order_by(UniversityEditorialEventCategoryLinkModel.category_id)
        ).all()
        return EditorialEventRelations(eventId=event_id, unitIds=tuple(units), programIds=tuple(programs), categoryIds=tuple(categories))

    def list_agenda(self, event_id: UniversityEventId) -> tuple[AgendaItem, ...]:
        models = self._session.scalars(
            select(UniversityEditorialAgendaItemModel)
            .where(UniversityEditorialAgendaItemModel.event_id == event_id)
            .order_by(UniversityEditorialAgendaItemModel.position)
        ).all()
        return tuple(_to_agenda(item) for item in models)

    def list_events(
        self,
        university_id: UniversityId,
        *,
        status: EditorialEventStatus | None = None,
        kind: EventKind | None = None,
        format: EventFormat | None = None,
        public_only: bool = False,
    ) -> tuple[EditorialEvent, ...]:
        statement = select(UniversityEditorialEventModel).where(UniversityEditorialEventModel.university_id == university_id)
        if status is not None:
            statement = statement.where(UniversityEditorialEventModel.status == status.value)
        if public_only:
            statement = statement.where(UniversityEditorialEventModel.status == EditorialEventStatus.PUBLISHED.value)
        if kind is not None:
            statement = statement.where(UniversityEditorialEventModel.kind == kind.value)
        if format is not None:
            statement = statement.where(UniversityEditorialEventModel.format == format.value)
        models = self._session.scalars(statement.order_by(UniversityEditorialEventModel.starts_at, UniversityEditorialEventModel.event_id)).all()
        return tuple(_to_event(model) for model in models)

    def venue_belongs(self, university_id: UniversityId, venue_id: str) -> bool:
        return self._session.scalar(
            select(VenueUniversityLinkModel.venue_id).where(
                VenueUniversityLinkModel.venue_id == venue_id,
                VenueUniversityLinkModel.university_id == university_id,
            )
        ) is not None

    def list_snapshots(
        self,
        university_id: UniversityId,
        *,
        status: EditorialEventStatus | None = None,
        kind: EventKind | None = None,
        format: EventFormat | None = None,
        public_only: bool = False,
    ) -> tuple[EditorialEventSnapshot, ...]:
        events = self.list_events(
            university_id,
            status=status,
            kind=kind,
            format=format,
            public_only=public_only,
        )
        if not events:
            return ()
        event_ids = tuple(item.event_id for item in events)
        agenda_by_event: dict[str, list[AgendaItem]] = {event_id: [] for event_id in event_ids}
        for agenda_item in self._session.scalars(
            select(UniversityEditorialAgendaItemModel)
            .where(UniversityEditorialAgendaItemModel.event_id.in_(event_ids))
            .order_by(UniversityEditorialAgendaItemModel.event_id, UniversityEditorialAgendaItemModel.position)
        ).all():
            agenda_by_event[agenda_item.event_id].append(_to_agenda(agenda_item))
        units_by_event: dict[str, list[str]] = {event_id: [] for event_id in event_ids}
        for unit_link in self._session.scalars(
            select(UniversityEditorialEventUnitLinkModel)
            .where(UniversityEditorialEventUnitLinkModel.event_id.in_(event_ids))
            .order_by(UniversityEditorialEventUnitLinkModel.event_id, UniversityEditorialEventUnitLinkModel.unit_id)
        ).all():
            units_by_event[unit_link.event_id].append(unit_link.unit_id)
        programs_by_event: dict[str, list[str]] = {event_id: [] for event_id in event_ids}
        for program_link in self._session.scalars(
            select(UniversityEditorialEventProgramLinkModel)
            .where(UniversityEditorialEventProgramLinkModel.event_id.in_(event_ids))
            .order_by(UniversityEditorialEventProgramLinkModel.event_id, UniversityEditorialEventProgramLinkModel.program_id)
        ).all():
            programs_by_event[program_link.event_id].append(program_link.program_id)
        categories_by_event: dict[str, list[str]] = {event_id: [] for event_id in event_ids}
        for category_link in self._session.scalars(
            select(UniversityEditorialEventCategoryLinkModel)
            .where(UniversityEditorialEventCategoryLinkModel.event_id.in_(event_ids))
            .order_by(UniversityEditorialEventCategoryLinkModel.event_id, UniversityEditorialEventCategoryLinkModel.category_id)
        ).all():
            categories_by_event[category_link.event_id].append(category_link.category_id)
        return tuple(
            EditorialEventSnapshot(
                event=event,
                relations=EditorialEventRelations(
                    eventId=event.event_id,
                    unitIds=tuple(units_by_event[event.event_id]),
                    programIds=tuple(programs_by_event[event.event_id]),
                    categoryIds=tuple(categories_by_event[event.event_id]),
                ),
                agenda=tuple(agenda_by_event[event.event_id]),
            )
            for event in events
        )

    def create_event(self, event: EditorialEvent, relations: EditorialEventRelations, agenda: tuple[AgendaItem, ...]) -> EditorialEvent:
        try:
            self._session.add(UniversityEditorialEventModel(**_event_values(event)))
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            logger.warning("editorial_event_write_rejected outcome=conflict")
            raise ConflictError("Editorial event conflicts with existing data") from exc
        self._add_relations(relations)
        self._add_agenda(agenda)
        return self._commit_and_return(event.event_id)

    def update_event(
        self,
        event: EditorialEvent,
        relations: EditorialEventRelations,
        agenda: tuple[AgendaItem, ...],
        *,
        expected_revision: int,
    ) -> EditorialEvent:
        model = self._session.get(UniversityEditorialEventModel, event.event_id)
        if model is None or model.revision != expected_revision:
            raise ConflictError("Event revision is stale")
        for key, value in _event_values(event).items():
            if key not in {"event_id", "created_at", "created_by_account_id"}:
                setattr(model, key, value)
        model.revision = expected_revision + 1
        self._session.execute(delete(UniversityEditorialEventUnitLinkModel).where(UniversityEditorialEventUnitLinkModel.event_id == event.event_id))
        self._session.execute(delete(UniversityEditorialEventProgramLinkModel).where(UniversityEditorialEventProgramLinkModel.event_id == event.event_id))
        self._session.execute(delete(UniversityEditorialEventCategoryLinkModel).where(UniversityEditorialEventCategoryLinkModel.event_id == event.event_id))
        self._session.execute(delete(UniversityEditorialAgendaItemModel).where(UniversityEditorialAgendaItemModel.event_id == event.event_id))
        self._add_relations(relations)
        self._add_agenda(agenda)
        return self._commit_and_return(event.event_id)

    def _add_relations(self, relations: EditorialEventRelations) -> None:
        self._session.add_all(
            [UniversityEditorialEventUnitLinkModel(event_id=relations.event_id, unit_id=unit_id) for unit_id in relations.unit_ids]
            + [UniversityEditorialEventProgramLinkModel(event_id=relations.event_id, program_id=program_id) for program_id in relations.program_ids]
            + [UniversityEditorialEventCategoryLinkModel(event_id=relations.event_id, category_id=category_id) for category_id in relations.category_ids]
        )

    def _add_agenda(self, agenda: tuple[AgendaItem, ...]) -> None:
        self._session.add_all(UniversityEditorialAgendaItemModel(**_agenda_values(item)) for item in agenda)

    def _commit_and_return(self, event_id: UniversityEventId) -> EditorialEvent:
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            logger.warning("editorial_event_write_rejected outcome=conflict")
            raise ConflictError("Editorial event conflicts with existing data") from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.error("editorial_event_write_failed")
            raise RuntimeError("Editorial event persistence failed") from exc
        model = self._session.get(UniversityEditorialEventModel, event_id)
        if model is None:
            raise RuntimeError("Editorial event disappeared after write")
        return _to_event(model)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_event(model: UniversityEditorialEventModel) -> EditorialEvent:
    return EditorialEvent(
        eventId=model.event_id,
        universityId=model.university_id,
        slug=model.slug,
        title=model.title,
        kind=EventKind(model.kind),
        format=EventFormat(model.format),
        startsAt=_utc(model.starts_at),
        endsAt=_utc(model.ends_at) if model.ends_at is not None else None,
        description=model.description,
        registrationUrl=model.registration_url,
        venueId=model.venue_id,
        locationLabel=model.location_label,
        locationAddress=model.location_address,
        onlineUrl=model.online_url,
        status=EditorialEventStatus(model.status),
        audienceMode=EditorialAudienceMode(model.audience_mode),
        revision=model.revision,
        createdByAccountId=model.created_by_account_id,
        updatedByAccountId=model.updated_by_account_id,
        createdAt=_utc(model.created_at),
        updatedAt=_utc(model.updated_at),
        publishedAt=_utc(model.published_at) if model.published_at is not None else None,
        archivedAt=_utc(model.archived_at) if model.archived_at is not None else None,
    )


def _to_agenda(model: UniversityEditorialAgendaItemModel) -> AgendaItem:
    return AgendaItem(
        itemId=model.item_id,
        eventId=model.event_id,
        position=model.position,
        title=model.title,
        description=model.description,
        startsAt=_utc(model.starts_at) if model.starts_at is not None else None,
        endsAt=_utc(model.ends_at) if model.ends_at is not None else None,
        locationLabel=model.location_label,
        speakerLabel=model.speaker_label,
        revision=model.revision,
    )


def _event_values(event: EditorialEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "university_id": event.university_id,
        "slug": event.slug,
        "title": event.title,
        "kind": event.kind.value,
        "format": event.format.value,
        "starts_at": _utc(event.starts_at),
        "ends_at": _utc(event.ends_at) if event.ends_at else None,
        "description": event.description,
        "registration_url": event.registration_url,
        "venue_id": event.venue_id,
        "location_label": event.location_label,
        "location_address": event.location_address,
        "online_url": event.online_url,
        "status": event.status.value,
        "audience_mode": event.audience_mode.value,
        "revision": event.revision,
        "created_by_account_id": event.created_by_account_id,
        "updated_by_account_id": event.updated_by_account_id,
        "created_at": _utc(event.created_at),
        "updated_at": _utc(event.updated_at),
        "published_at": _utc(event.published_at) if event.published_at else None,
        "archived_at": _utc(event.archived_at) if event.archived_at else None,
    }


def _agenda_values(item: AgendaItem) -> dict[str, object]:
    return {
        "item_id": item.item_id,
        "event_id": item.event_id,
        "position": item.position,
        "title": item.title,
        "description": item.description,
        "starts_at": _utc(item.starts_at) if item.starts_at else None,
        "ends_at": _utc(item.ends_at) if item.ends_at else None,
        "location_label": item.location_label,
        "speaker_label": item.speaker_label,
        "revision": item.revision,
    }


__all__ = ["SqlAlchemyUniversityEditorialEventRepository"]
