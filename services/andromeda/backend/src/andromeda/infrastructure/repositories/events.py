from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from pydantic import HttpUrl, TypeAdapter

from andromeda.modules.events.contracts.public import EventFilters
from andromeda.modules.events.contracts.results import EventListResult
from andromeda.modules.events.domain.entities import Event, EventFormat, EventKind, Venue
from andromeda.modules.events.repository.ports import EventRepository
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.errors import ContractError, ErrorCode
from andromeda.shared.contracts.ids import EventId, canonical_program_id
from andromeda.shared.contracts.provenance import SourceAttribution

from ..database.models import (
    EventDepartmentLinkModel,
    EventModel,
    EventProgramLinkModel,
    EventUniversityLinkModel,
    ProgramModel,
    UniversityModel,
    VenueModel,
)


logger = logging.getLogger("andromeda.infrastructure.repositories.events")
_HTTP_URL = TypeAdapter(HttpUrl)


@dataclass(frozen=True, slots=True)
class EventSyncStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    venues: int = 0
    links: int = 0


class SqlAlchemyEventRepository(EventRepository):
    """Infrastructure adapter for event reads and source-scoped projection sync."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._dialect = session.get_bind().dialect.name

    def list(self, filters: EventFilters) -> EventListResult:
        logger.debug(
            "event_read_start dialect=%s from=%s to=%s kind=%s format=%s recommended=%s limit=%d",
            self._dialect,
            filters.from_date,
            filters.to_date,
            filters.kind.value if filters.kind else None,
            filters.format.value if filters.format else None,
            filters.recommended,
            filters.limit,
        )
        query = select(EventModel)
        query = self._apply_filters(query, filters)
        total = int(self._session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rows = self._session.execute(query.order_by(EventModel.starts_at.asc(), EventModel.id.asc()).limit(filters.limit)).scalars().all()
        items = self._to_contracts(rows)
        if not items:
            logger.warning("event_read_empty recommended=%s total=%d", filters.recommended, total)
        logger.info("event_read_complete result_count=%d total=%d", len(items), total)
        return EventListResult(items=items, total=total)

    def get(self, event_id: EventId) -> Event | None:
        logger.debug("event_read_detail_start event_id=%s", event_id)
        row = self._session.get(EventModel, event_id)
        if row is None:
            logger.warning("event_read_detail_empty event_id=%s", event_id)
            return None
        result = self._to_contracts((row,))[0]
        logger.info("event_read_detail_complete event_id=%s", event_id)
        return result

    def sync(self, events: Iterable[Event], *, source_scope: str | None) -> EventSyncStats:
        values = tuple(events)
        if source_scope is None:
            logger.debug("event_projection_skip source_scope=absent event_count=%d", len(values))
            return EventSyncStats()
        logger.debug("event_projection_start source_scope=%s event_count=%d", source_scope, len(values))
        inserted = updated = unchanged = removed = venue_count = link_count = 0
        expected_ids: set[str] = set()
        expected_venue_ids: set[str] = set()
        for event in values:
            for university_id in event.university_ids:
                if self._session.get(UniversityModel, university_id) is None:
                    raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Event university does not exist: {university_id}")
            for program_id in event.program_ids:
                if self._session.get(ProgramModel, program_id) is None:
                    raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Event program does not exist: {program_id}")
            primary = event.provenance[0]
            venue_id = None
            if event.venue is not None:
                venue_id = event.venue.id
                expected_venue_ids.add(venue_id)
                venue_outcome = self._upsert_venue(event.venue, primary)
                if venue_outcome == "inserted":
                    venue_count += 1
                # Models intentionally have no ORM relationships; make the
                # venue visible before an event row references it.
                self._session.flush()
            event_values = {
                "id": event.id,
                "title": event.title,
                "kind": event.kind.value,
                "format": event.format.value,
                "starts_at": event.starts_at,
                "ends_at": event.ends_at,
                "description": event.description,
                "registration_url": str(event.registration_url) if event.registration_url is not None else None,
                "venue_id": venue_id,
                "source_kind": primary.kind.value,
                "source_url": str(primary.url),
                "captured_at": primary.captured_at,
                "content_sha256": primary.content_sha256,
                "source_locator": primary.locator,
            }
            outcome = self._upsert(EventModel, event.id, event_values, immutable_fields=())
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            else:
                unchanged += 1
            expected_ids.add(event.id)
        # Flush event rows before inserting their child link collections.
        self._session.flush()
        for event in values:
            self._replace_links(event)
            link_count += len(event.university_ids) + len(event.department_ids) + len(event.program_ids)
        stale_ids = set(
            self._session.scalars(select(EventModel.id).where(EventModel.source_kind == source_scope)).all()
        ) - expected_ids
        if stale_ids:
            self._session.execute(delete(EventDepartmentLinkModel).where(EventDepartmentLinkModel.event_id.in_(stale_ids)))
            self._session.execute(delete(EventProgramLinkModel).where(EventProgramLinkModel.event_id.in_(stale_ids)))
            self._session.execute(delete(EventUniversityLinkModel).where(EventUniversityLinkModel.event_id.in_(stale_ids)))
            self._session.execute(delete(EventModel).where(EventModel.id.in_(stale_ids)))
            removed = len(stale_ids)
            logger.warning("event_projection_remove_stale source_scope=%s count=%d", source_scope, removed)
        referenced = select(EventModel.venue_id).where(EventModel.venue_id.is_not(None))
        self._session.execute(
            delete(VenueModel).where(
                VenueModel.source_kind == source_scope,
                VenueModel.id.not_in(expected_venue_ids),
                VenueModel.id.not_in(referenced),
            )
        )
        logger.info(
            "event_projection_complete source_scope=%s events_inserted=%d events_updated=%d events_unchanged=%d events_removed=%d venues=%d links=%d",
            source_scope,
            inserted,
            updated,
            unchanged,
            removed,
            venue_count,
            link_count,
        )
        return EventSyncStats(inserted, updated, unchanged, removed, venue_count, link_count)

    def _apply_filters(self, query: Any, filters: EventFilters) -> Any:
        if filters.from_date is not None:
            query = query.where(EventModel.starts_at >= filters.from_date)
        if filters.to_date is not None:
            query = query.where(EventModel.starts_at <= filters.to_date)
        if filters.kind is not None:
            query = query.where(EventModel.kind == filters.kind.value)
        if filters.format is not None:
            query = query.where(EventModel.format == filters.format.value)
        if filters.university_id is not None:
            query = query.where(
                select(EventUniversityLinkModel.event_id)
                .where(EventUniversityLinkModel.event_id == EventModel.id, EventUniversityLinkModel.university_id == filters.university_id)
                .exists()
            )
        if filters.department_id is not None:
            query = query.where(
                select(EventDepartmentLinkModel.event_id)
                .where(EventDepartmentLinkModel.event_id == EventModel.id, EventDepartmentLinkModel.department_id == filters.department_id)
                .exists()
            )
        if filters.program_id is not None:
            program_id = canonical_program_id(filters.program_id)
            query = query.where(
                select(EventProgramLinkModel.event_id)
                .where(EventProgramLinkModel.event_id == EventModel.id, EventProgramLinkModel.program_id == program_id)
                .exists()
            )
        if filters.recommended:
            recommended_program_ids = tuple(canonical_program_id(program_id) for program_id in filters.recommended_program_ids)
            query = query.where(
                select(EventProgramLinkModel.event_id)
                .where(
                    EventProgramLinkModel.event_id == EventModel.id,
                    EventProgramLinkModel.program_id.in_(recommended_program_ids),
                )
                .exists()
            )
        return query

    def _replace_links(self, event: Event) -> None:
        self._session.execute(delete(EventUniversityLinkModel).where(EventUniversityLinkModel.event_id == event.id))
        self._session.execute(delete(EventDepartmentLinkModel).where(EventDepartmentLinkModel.event_id == event.id))
        self._session.execute(delete(EventProgramLinkModel).where(EventProgramLinkModel.event_id == event.id))
        self._session.add_all([EventUniversityLinkModel(event_id=event.id, university_id=value) for value in event.university_ids])
        self._session.add_all([EventDepartmentLinkModel(event_id=event.id, department_id=value) for value in event.department_ids])
        self._session.add_all([EventProgramLinkModel(event_id=event.id, program_id=value) for value in event.program_ids])

    def _upsert_venue(self, venue: Venue, provenance: SourceAttribution) -> str:
        existing = self._session.get(VenueModel, venue.id)
        if existing is not None and existing.source_kind == SourceKind.BMSTU_CAMPUS_POINTS.value:
            # Campus source is authoritative for shared point metadata. An
            # event-only/live run must not erase a previously captured campus
            # projection merely because campus capture is unavailable.
            logger.debug("event_projection_venue_preserved identity=%s reason=campus_source_precedence", venue.id)
            return "unchanged"
        values = {
            "id": venue.id,
            "point_type": "event_venue",
            "name": venue.name,
            "address": venue.address,
            "latitude": venue.latitude,
            "longitude": venue.longitude,
            "source_kind": provenance.kind.value,
            "source_url": str(provenance.url),
            "captured_at": provenance.captured_at,
            "content_sha256": provenance.content_sha256,
            "source_locator": provenance.locator,
        }
        return self._upsert(VenueModel, venue.id, values, immutable_fields=())

    def _upsert(self, model: type[Any], identity: str, values: Mapping[str, object], *, immutable_fields: tuple[str, ...]) -> str:
        existing = self._session.get(model, identity)
        if existing is None:
            self._session.add(model(**values))
            logger.debug("event_projection_insert model=%s identity=%s", model.__name__, identity)
            return "inserted"
        immutable = set(immutable_fields)
        changed: list[str] = []
        for field, expected in values.items():
            if field == "id":
                continue
            actual = getattr(existing, field)
            if not _values_equal(actual, expected):
                if field in immutable:
                    raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Event identity conflict: {identity}")
                setattr(existing, field, expected)
                changed.append(field)
        if changed:
            logger.debug("event_projection_update model=%s identity=%s fields=%s", model.__name__, identity, ",".join(changed))
            return "updated"
        return "unchanged"

    def _to_contracts(self, rows: Sequence[EventModel]) -> tuple[Event, ...]:
        if not rows:
            return ()
        logger.debug("[FIX:events-batch] event_read_batch_start event_count=%d", len(rows))
        try:
            event_ids = tuple(row.id for row in rows)
            university_by_event = self._load_links(EventUniversityLinkModel, event_ids, "university_id")
            department_by_event = self._load_links(EventDepartmentLinkModel, event_ids, "department_id")
            program_by_event = self._load_links(EventProgramLinkModel, event_ids, "program_id")
            venue_ids = tuple(row.venue_id for row in rows if row.venue_id is not None)
            venues = (
                {venue.id: venue for venue in self._session.scalars(select(VenueModel).where(VenueModel.id.in_(venue_ids))).all()}
                if venue_ids
                else {}
            )
            contracts = tuple(
                self._to_contract(
                    row,
                    university_ids=tuple(university_by_event.get(row.id, ())),
                    department_ids=tuple(department_by_event.get(row.id, ())),
                    program_ids=tuple(program_by_event.get(row.id, ())),
                    venue_row=venues.get(row.venue_id) if row.venue_id is not None else None,
                )
                for row in rows
            )
        except Exception:
            logger.exception("[FIX:events-batch] event_read_batch_failed event_count=%d", len(rows))
            raise
        logger.info(
            "[FIX:events-batch] event_read_batch_complete event_count=%d venue_count=%d",
            len(contracts),
            len(venues),
        )
        return contracts

    def _load_links(self, model: type[Any], event_ids: tuple[str, ...], value_column: str) -> dict[str, tuple[str, ...]]:
        event_column = getattr(model, "event_id")
        selected_column = getattr(model, value_column)
        result: dict[str, tuple[str, ...]] = {event_id: () for event_id in event_ids}
        rows = self._session.execute(
            select(event_column, selected_column)
            .where(event_column.in_(event_ids))
            .order_by(event_column, selected_column)
        ).all()
        for event_id, value in rows:
            result[event_id] = (*result[event_id], value)
        return result

    @staticmethod
    def _to_contract(
        row: EventModel,
        *,
        university_ids: tuple[str, ...],
        department_ids: tuple[str, ...],
        program_ids: tuple[str, ...],
        venue_row: VenueModel | None,
    ) -> Event:
        primary = SourceAttribution(
            kind=SourceKind(row.source_kind),
            url=_HTTP_URL.validate_python(row.source_url),
            captured_at=_aware(row.captured_at),
            content_sha256=row.content_sha256,
            locator=row.source_locator,
        )
        return Event(
            id=row.id,
            title=row.title,
            kind=EventKind(row.kind),
            format=EventFormat(row.format),
            starts_at=_aware(row.starts_at),
            ends_at=_aware(row.ends_at) if row.ends_at is not None else None,
            description=row.description,
            registration_url=_HTTP_URL.validate_python(row.registration_url) if row.registration_url is not None else None,
            university_ids=university_ids,
            department_ids=department_ids,
            program_ids=program_ids,
            venue=SqlAlchemyEventRepository._venue_contract(venue_row) if venue_row is not None else None,
            provenance=(primary,),
        )

    @staticmethod
    def _venue_contract(row: VenueModel) -> Venue:
        return Venue(
            id=row.id,
            name=row.name,
            address=row.address,
            latitude=row.latitude,
            longitude=row.longitude,
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None and value.utcoffset() is not None else value.replace(tzinfo=timezone.utc)


def _values_equal(actual: object, expected: object) -> bool:
    if isinstance(actual, datetime) and isinstance(expected, datetime):
        return _aware(actual).astimezone(timezone.utc) == _aware(expected).astimezone(timezone.utc)
    return actual == expected or str(actual) == str(expected)


__all__ = ["EventSyncStats", "SqlAlchemyEventRepository"]
