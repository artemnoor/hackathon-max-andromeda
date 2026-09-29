from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import uuid4

from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.shared.contracts.errors import ConflictError, NotFoundError, ValidationError
from andromeda.shared.contracts.ids import AccountId, ProgramId, UniversityCategoryId, UniversityEventId, UniversityId, UniversityUnitId, VenueId

from ..contracts.catalog import EditorialStatus, EditorialVisibility
from ..contracts.events import AgendaItem, EditorialAudienceMode, EditorialEvent, EditorialEventRelations, EditorialEventSnapshot, EditorialEventStatus
from ..repository.catalog_ports import UniversityCatalogCanonicalReader, UniversityCatalogReader
from ..repository.event_ports import UniversityEditorialEventReader, UniversityEditorialEventWriter


logger = logging.getLogger("andromeda.modules.university_admin.events")


class UniversityEditorialEventService:
    def __init__(
        self,
        reader: UniversityEditorialEventReader,
        writer: UniversityEditorialEventWriter,
        catalog: UniversityCatalogReader,
        canonical: UniversityCatalogCanonicalReader,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._catalog = catalog
        self._canonical = canonical

    def create_event(
        self,
        *,
        university_id: UniversityId,
        account_id: AccountId,
        slug: str,
        title: str,
        kind: EventKind,
        format: EventFormat,
        starts_at: datetime,
        ends_at: datetime | None,
        description: str | None,
        registration_url: str | None,
        venue_id: VenueId | None,
        location_label: str | None,
        location_address: str | None,
        online_url: str | None,
        audience_mode: EditorialAudienceMode,
        unit_ids: tuple[UniversityUnitId, ...],
        program_ids: tuple[ProgramId, ...],
        category_ids: tuple[UniversityCategoryId, ...],
        agenda: tuple[AgendaItem, ...],
    ) -> EditorialEventSnapshot:
        now = _now()
        event_id: UniversityEventId = f"university-event:{university_id.removeprefix('university:')}:{uuid4().hex}"
        event = EditorialEvent(
            eventId=event_id,
            universityId=university_id,
            slug=slug,
            title=title,
            kind=kind,
            format=format,
            startsAt=starts_at,
            endsAt=ends_at,
            description=description,
            registrationUrl=registration_url,
            venueId=venue_id,
            locationLabel=location_label,
            locationAddress=location_address,
            onlineUrl=online_url,
            status=EditorialEventStatus.DRAFT,
            audienceMode=audience_mode,
            revision=1,
            createdByAccountId=account_id,
            updatedByAccountId=account_id,
            createdAt=now,
            updatedAt=now,
        )
        relations = EditorialEventRelations(eventId=event_id, unitIds=unit_ids, programIds=program_ids, categoryIds=category_ids)
        self._validate(event, relations, agenda, publishing=False)
        saved = self._writer.create_event(event, relations, agenda)
        logger.info("editorial_event_created university_id=%s event_id=%s status=%s revision=%d", university_id, saved.event_id, saved.status.value, saved.revision)
        return EditorialEventSnapshot(event=saved, relations=relations, agenda=agenda)

    def update_event(
        self,
        *,
        university_id: UniversityId,
        event_id: UniversityEventId,
        account_id: AccountId,
        expected_revision: int,
        title: str,
        kind: EventKind,
        format: EventFormat,
        starts_at: datetime,
        ends_at: datetime | None,
        description: str | None,
        registration_url: str | None,
        venue_id: VenueId | None,
        location_label: str | None,
        location_address: str | None,
        online_url: str | None,
        audience_mode: EditorialAudienceMode,
        unit_ids: tuple[UniversityUnitId, ...],
        program_ids: tuple[ProgramId, ...],
        category_ids: tuple[UniversityCategoryId, ...],
        agenda: tuple[AgendaItem, ...],
    ) -> EditorialEventSnapshot:
        current = self._require_event(university_id, event_id)
        if current.status is EditorialEventStatus.ARCHIVED:
            raise ConflictError("Archived event cannot be updated")
        updated = current.model_copy(
            update={
                "title": title,
                "kind": kind,
                "format": format,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "description": description,
                "registration_url": registration_url,
                "venue_id": venue_id,
                "location_label": location_label,
                "location_address": location_address,
                "online_url": online_url,
                "audience_mode": audience_mode,
                "updated_by_account_id": account_id,
                "updated_at": _now(),
            }
        )
        relations = EditorialEventRelations(eventId=event_id, unitIds=unit_ids, programIds=program_ids, categoryIds=category_ids)
        self._validate(updated, relations, agenda, publishing=updated.status is EditorialEventStatus.PUBLISHED)
        saved = self._writer.update_event(updated, relations, agenda, expected_revision=expected_revision)
        logger.info("editorial_event_updated university_id=%s event_id=%s status=%s revision=%d", university_id, event_id, saved.status.value, saved.revision)
        return EditorialEventSnapshot(event=saved, relations=relations, agenda=agenda)

    def publish_event(self, *, university_id: UniversityId, event_id: UniversityEventId, account_id: AccountId, expected_revision: int) -> EditorialEventSnapshot:
        current = self._require_event(university_id, event_id)
        if current.status is not EditorialEventStatus.DRAFT:
            raise ConflictError("Only draft events can be published")
        relations = self._reader.get_relations(event_id)
        agenda = self._reader.list_agenda(event_id)
        self._validate(current, relations, agenda, publishing=True)
        updated = current.model_copy(update={"status": EditorialEventStatus.PUBLISHED, "published_at": _now(), "updated_by_account_id": account_id, "updated_at": _now()})
        saved = self._writer.update_event(updated, relations, agenda, expected_revision=expected_revision)
        logger.info("editorial_event_published university_id=%s event_id=%s status=%s revision=%d", university_id, event_id, saved.status.value, saved.revision)
        return EditorialEventSnapshot(event=saved, relations=relations, agenda=agenda)

    def archive_event(self, *, university_id: UniversityId, event_id: UniversityEventId, account_id: AccountId, expected_revision: int) -> EditorialEventSnapshot:
        current = self._require_event(university_id, event_id)
        if current.status is EditorialEventStatus.ARCHIVED:
            raise ConflictError("Event is already archived")
        relations = self._reader.get_relations(event_id)
        agenda = self._reader.list_agenda(event_id)
        updated = current.model_copy(update={"status": EditorialEventStatus.ARCHIVED, "archived_at": _now(), "updated_by_account_id": account_id, "updated_at": _now()})
        saved = self._writer.update_event(updated, relations, agenda, expected_revision=expected_revision)
        logger.info("editorial_event_archived university_id=%s event_id=%s status=%s revision=%d", university_id, event_id, saved.status.value, saved.revision)
        return EditorialEventSnapshot(event=saved, relations=relations, agenda=agenda)

    def replace_agenda(self, *, university_id: UniversityId, event_id: UniversityEventId, account_id: AccountId, expected_revision: int, agenda: tuple[AgendaItem, ...]) -> EditorialEventSnapshot:
        current = self._require_event(university_id, event_id)
        relations = self._reader.get_relations(event_id)
        self._validate_agenda(current, agenda)
        updated = current.model_copy(update={"updated_by_account_id": account_id, "updated_at": _now()})
        saved = self._writer.update_event(updated, relations, agenda, expected_revision=expected_revision)
        return EditorialEventSnapshot(event=saved, relations=relations, agenda=agenda)

    def get_admin_event(self, university_id: UniversityId, event_id: UniversityEventId) -> EditorialEventSnapshot:
        event = self._require_event(university_id, event_id)
        return EditorialEventSnapshot(event=event, relations=self._reader.get_relations(event_id), agenda=self._reader.list_agenda(event_id))

    def list_admin_events(self, university_id: UniversityId, status: EditorialEventStatus | None = None) -> tuple[EditorialEventSnapshot, ...]:
        return self._reader.list_snapshots(university_id, status=status)

    def get_public_event(self, university_id: UniversityId, event_id: UniversityEventId) -> EditorialEventSnapshot:
        for snapshot in self._public_snapshots(university_id):
            if snapshot.event.event_id == event_id:
                return snapshot
        raise NotFoundError("Resource was not found")

    def list_public_events(self, university_id: UniversityId, *, kind: EventKind | None = None, format: EventFormat | None = None) -> tuple[EditorialEventSnapshot, ...]:
        return self._public_snapshots(university_id, kind=kind, format=format)

    def _public_snapshots(self, university_id: UniversityId, *, kind: EventKind | None = None, format: EventFormat | None = None) -> tuple[EditorialEventSnapshot, ...]:
        units = {item.unit_id: item for item in self._catalog.list_units(university_id, include_archived=False) if item.status is not EditorialStatus.ARCHIVED}
        categories = {item.category_id: item for item in self._catalog.list_categories(university_id, include_archived=False) if item.status is EditorialStatus.PUBLISHED}
        programs = {item.id for item in self._canonical.list_programs(university_id)}
        programs -= {item.program_id for item in self._catalog.list_program_editorials(university_id) if item.visibility is EditorialVisibility.HIDDEN}
        snapshots = self._reader.list_snapshots(university_id, kind=kind, format=format, public_only=True)
        result: list[EditorialEventSnapshot] = []
        for snapshot in snapshots:
            relations = snapshot.relations.model_copy(
                update={
                    "unit_ids": tuple(item for item in snapshot.relations.unit_ids if item in units),
                    "program_ids": tuple(item for item in snapshot.relations.program_ids if item in programs),
                    "category_ids": tuple(item for item in snapshot.relations.category_ids if item in categories),
                }
            )
            if snapshot.event.audience_mode is EditorialAudienceMode.SELECTED_UNITS and not relations.unit_ids:
                continue
            if snapshot.event.audience_mode is EditorialAudienceMode.SELECTED_PROGRAMS and not relations.program_ids:
                continue
            result.append(snapshot.model_copy(update={"relations": relations}))
        return tuple(result)

    def _require_event(self, university_id: UniversityId, event_id: UniversityEventId) -> EditorialEvent:
        event = self._reader.get_event(event_id)
        if event is None or event.university_id != university_id:
            raise NotFoundError("Resource was not found")
        return event

    def _validate(self, event: EditorialEvent, relations: EditorialEventRelations, agenda: tuple[AgendaItem, ...], *, publishing: bool) -> None:
        if relations.event_id != event.event_id:
            raise ValidationError("Event relation scope is invalid")
        if len(relations.unit_ids) != len(set(relations.unit_ids)) or len(relations.program_ids) != len(set(relations.program_ids)) or len(relations.category_ids) != len(set(relations.category_ids)):
            raise ValidationError("Event relations must be unique")
        self._validate_agenda(event, agenda)
        units = {item.unit_id: item for item in self._catalog.list_units(event.university_id)}
        categories = {item.category_id: item for item in self._catalog.list_categories(event.university_id)}
        if any(unit_id not in units for unit_id in relations.unit_ids):
            raise ValidationError("Event unit is outside university scope")
        if any(category_id not in categories for category_id in relations.category_ids):
            raise ValidationError("Event category is outside university scope")
        if any(categories[category_id].category_kind.value not in {"event", "general"} for category_id in relations.category_ids):
            raise ValidationError("Event category kind is invalid")
        if any(not self._canonical.program_belongs(event.university_id, program_id) for program_id in relations.program_ids):
            raise ValidationError("Event program is outside university scope")
        if event.venue_id is not None and not self._reader.venue_belongs(event.university_id, event.venue_id):
            raise ValidationError("Event venue is outside university scope")
        if event.audience_mode is EditorialAudienceMode.ALL_UNIVERSITY and (relations.unit_ids or relations.program_ids):
            raise ValidationError("all_university events cannot have selected audience links")
        if event.audience_mode is EditorialAudienceMode.UNAFFILIATED and (relations.unit_ids or relations.program_ids):
            raise ValidationError("unaffiliated events cannot have selected audience links")
        if event.audience_mode is EditorialAudienceMode.SELECTED_UNITS and not relations.unit_ids:
            raise ValidationError("selected_units audience requires a unit")
        if event.audience_mode is EditorialAudienceMode.SELECTED_PROGRAMS and not relations.program_ids:
            raise ValidationError("selected_programs audience requires a program")
        if publishing:
            if any(units[unit_id].status is not EditorialStatus.PUBLISHED for unit_id in relations.unit_ids):
                raise ValidationError("Published event cannot target an unpublished unit")
            if any(categories[category_id].status is not EditorialStatus.PUBLISHED for category_id in relations.category_ids):
                raise ValidationError("Published event cannot target an unpublished category")
            if any(program_id not in {program.id for program in self._canonical.list_programs(event.university_id)} for program_id in relations.program_ids):
                raise ValidationError("Published event cannot target an unavailable program")

    def _validate_agenda(self, event: EditorialEvent, agenda: tuple[AgendaItem, ...]) -> None:
        positions = tuple(item.position for item in agenda)
        if len(positions) != len(set(positions)) or positions != tuple(sorted(positions)):
            raise ValidationError("Agenda positions must be unique and ordered")
        for item in agenda:
            if item.event_id != event.event_id:
                raise ValidationError("Agenda item belongs to another event")
            if item.starts_at is not None and item.starts_at < event.starts_at:
                raise ValidationError("Agenda starts before event")
            if item.ends_at is not None and event.ends_at is not None and item.ends_at > event.ends_at:
                raise ValidationError("Agenda ends after event")


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["UniversityEditorialEventService"]
