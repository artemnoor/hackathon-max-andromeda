"""Persistence adapter for the shared venue-backed campus projection."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from andromeda.modules.campus.contracts.public import CampusEventFilters, CampusPoint, CampusPointDetail, CampusPointFilters
from andromeda.modules.campus.contracts.results import CampusPointDetailResult, CampusPointEventsResult, CampusPointListResult, CampusRecommendationResult
from andromeda.modules.campus.domain.entities import CampusDepartmentReference, CampusPointType, CampusProgramReference, CampusUniversityReference
from andromeda.modules.events.contracts.results import EventListResult
from andromeda.modules.events.domain.entities import Event
from andromeda.modules.campus.repository.ports import CampusPointReader
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.errors import ContractError, ErrorCode, NotFoundError
from andromeda.shared.contracts.provenance import SourceAttribution
from andromeda.shared.contracts.ids import canonical_program_id

from ..database.models import (
    EventModel,
    EventDepartmentLinkModel,
    EventProgramLinkModel,
    EventUniversityLinkModel,
    ProgramModel,
    UniversityModel,
    VenueDepartmentLinkModel,
    VenueModel,
    VenueProgramLinkModel,
    VenueUniversityLinkModel,
)


logger = logging.getLogger("andromeda.infrastructure.repositories.campus")
_HTTP_URL = TypeAdapter(HttpUrl)


@dataclass(frozen=True, slots=True)
class CampusSyncStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    links: int = 0


class SqlAlchemyCampusPointRepository(CampusPointReader):
    """Read and source-scoped sync adapter for campus points.

    The write side only owns point metadata and direct point links. Events and
    catalog entities remain owned by their existing repositories/tables.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._dialect = session.get_bind().dialect.name

    def list(self, filters: CampusPointFilters) -> CampusPointListResult:
        logger.debug(
            "campus_point_read_start dialect=%s university=%s department=%s program=%s point_type=%s limit=%d",
            self._dialect,
            filters.university_id,
            filters.department_id,
            filters.program_id,
            filters.point_type.value if filters.point_type else None,
            filters.limit,
        )
        query = self._point_query(filters)
        total = int(self._session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rows = self._session.execute(query.order_by(VenueModel.id.asc()).limit(filters.limit)).scalars().all()
        points = self._to_points(rows)
        if not points:
            logger.warning("campus_point_read_empty total=%d", total)
        logger.info("campus_point_read_complete result_count=%d total=%d", len(points), total)
        return CampusPointListResult(items=points, total=total)

    def get(self, point_id: str) -> CampusPointDetailResult | None:
        logger.debug("campus_point_detail_read_start point_id=%s", point_id)
        row = self._session.get(VenueModel, point_id)
        if row is None:
            logger.warning("campus_point_detail_read_empty point_id=%s", point_id)
            return None
        detail = self._to_details((row,))[0]
        logger.info("campus_point_detail_read_complete point_id=%s", point_id)
        return CampusPointDetailResult(point=detail)

    def events(self, point_id: str, filters: CampusEventFilters) -> CampusPointEventsResult:
        logger.debug(
            "campus_point_event_read_start point_id=%s from=%s to=%s recommended=%s limit=%d",
            point_id,
            filters.from_date,
            filters.to_date,
            filters.recommended,
            filters.limit,
        )
        if self._session.get(VenueModel, point_id) is None:
            raise NotFoundError("Campus point was not found")
        query = select(EventModel).where(EventModel.venue_id == point_id)
        query = self._apply_event_filters(query, filters)
        total = int(self._session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rows = self._session.execute(query.order_by(EventModel.starts_at.asc(), EventModel.id.asc()).limit(filters.limit)).scalars().all()
        events = self._event_contracts(rows)
        if not events:
            logger.warning("campus_point_event_read_empty point_id=%s total=%d", point_id, total)
        logger.info("campus_point_event_read_complete point_id=%s result_count=%d total=%d", point_id, len(events), total)
        return CampusPointEventsResult(point_id=point_id, events=EventListResult(items=events, total=total))

    def recommendations(self, program_ids: tuple[str, ...], *, limit: int) -> CampusRecommendationResult:
        resolved_program_ids = tuple(canonical_program_id(program_id) for program_id in program_ids)
        logger.debug("campus_recommendation_read_start program_count=%d limit=%d", len(program_ids), limit)
        point_query = select(VenueModel).where(self._program_point_condition(resolved_program_ids))
        point_rows = self._session.execute(point_query.order_by(VenueModel.id.asc()).limit(limit)).scalars().all()
        points = self._to_details(point_rows)

        event_query = select(EventModel).where(
            select(EventProgramLinkModel.event_id)
            .where(
                EventProgramLinkModel.event_id == EventModel.id,
                EventProgramLinkModel.program_id.in_(resolved_program_ids),
            )
            .exists()
        )
        event_rows = self._session.execute(
            event_query.order_by(EventModel.starts_at.asc(), EventModel.id.asc()).limit(limit)
        ).scalars().all()
        events = self._event_contracts(event_rows)
        events_with_point = tuple(event for event in events if event.venue is not None)
        events_without_point = tuple(event for event in events if event.venue is None)
        result = CampusRecommendationResult.from_parts(
            resolved_program_ids,
            points=points,
            events=events_with_point,
            events_without_point=events_without_point,
        )
        logger.info(
            "campus_recommendation_read_complete program_count=%d point_count=%d event_count=%d unplaced_event_count=%d",
            len(program_ids),
            len(points),
            len(events_with_point),
            len(events_without_point),
        )
        return result

    def sync(self, points: Iterable[CampusPoint], *, source_scope: str | None) -> CampusSyncStats:
        values = tuple(points)
        if source_scope is None:
            logger.debug("campus_projection_skip source_scope=absent point_count=%d", len(values))
            return CampusSyncStats()
        logger.debug("campus_projection_start dialect=%s source_scope=%s point_count=%d", self._dialect, source_scope, len(values))
        inserted = updated = unchanged = removed = links = 0
        expected_ids: set[str] = set()
        for point in values:
            self._validate_references(point)
            primary = point.provenance[0]
            outcome = self._upsert(
                VenueModel,
                point.id,
                {
                    "id": point.id,
                    "point_type": point.point_type.value,
                    "name": point.name,
                    "address": point.address,
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                    "source_kind": primary.kind.value,
                    "source_url": str(primary.url),
                    "captured_at": primary.captured_at,
                    "content_sha256": primary.content_sha256,
                    "source_locator": primary.locator,
                },
            )
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            else:
                unchanged += 1
            expected_ids.add(point.id)
        self._session.flush()
        for point in values:
            self._replace_links(point)
            links += len(point.university_ids) + len(point.department_ids) + len(point.program_ids)
        self._session.flush()

        current_ids = set(
            self._session.scalars(select(VenueModel.id).where(VenueModel.source_kind == source_scope)).all()
        )
        stale_ids = current_ids - expected_ids
        referenced_ids = set(
            self._session.scalars(select(EventModel.venue_id).where(EventModel.venue_id.is_not(None))).all()
        )
        for point_id in sorted(stale_ids):
            if point_id in referenced_ids:
                self._retain_event_fallback(point_id)
                removed += self._remove_links(point_id)
                logger.warning("campus_projection_stale_fallback point_id=%s", point_id)
                continue
            removed += self._remove_links(point_id)
            self._session.execute(delete(VenueModel).where(VenueModel.id == point_id))
            removed += 1
            logger.warning("campus_projection_remove_stale point_id=%s", point_id)
        logger.info(
            "campus_projection_complete source_scope=%s points_inserted=%d points_updated=%d points_unchanged=%d points_removed=%d links=%d",
            source_scope,
            inserted,
            updated,
            unchanged,
            removed,
            links,
        )
        return CampusSyncStats(inserted, updated, unchanged, removed, links)

    def _point_query(self, filters: CampusPointFilters) -> Any:
        query = select(VenueModel)
        if filters.point_type is not None:
            query = query.where(VenueModel.point_type == filters.point_type.value)
        if filters.university_id is not None:
            query = query.where(
                or_(
                    select(VenueUniversityLinkModel.venue_id)
                    .where(VenueUniversityLinkModel.venue_id == VenueModel.id, VenueUniversityLinkModel.university_id == filters.university_id)
                    .exists(),
                    select(EventUniversityLinkModel.event_id)
                    .join(EventModel, EventModel.id == EventUniversityLinkModel.event_id)
                    .where(EventModel.venue_id == VenueModel.id, EventUniversityLinkModel.university_id == filters.university_id)
                    .exists(),
                )
            )
        if filters.department_id is not None:
            query = query.where(
                or_(
                    select(VenueDepartmentLinkModel.venue_id)
                    .where(VenueDepartmentLinkModel.venue_id == VenueModel.id, VenueDepartmentLinkModel.department_id == filters.department_id)
                    .exists(),
                    select(EventDepartmentLinkModel.event_id)
                    .join(EventModel, EventModel.id == EventDepartmentLinkModel.event_id)
                    .where(EventModel.venue_id == VenueModel.id, EventDepartmentLinkModel.department_id == filters.department_id)
                    .exists(),
                )
            )
        if filters.program_id is not None:
            program_id = canonical_program_id(filters.program_id)
            query = query.where(
                or_(
                    select(VenueProgramLinkModel.venue_id)
                    .where(VenueProgramLinkModel.venue_id == VenueModel.id, VenueProgramLinkModel.program_id == program_id)
                    .exists(),
                    select(EventProgramLinkModel.event_id)
                    .join(EventModel, EventModel.id == EventProgramLinkModel.event_id)
                    .where(EventModel.venue_id == VenueModel.id, EventProgramLinkModel.program_id == program_id)
                    .exists(),
                )
            )
        return query

    @staticmethod
    def _program_point_condition(program_ids: tuple[str, ...]) -> Any:
        return or_(
            select(VenueProgramLinkModel.venue_id)
            .where(VenueProgramLinkModel.venue_id == VenueModel.id, VenueProgramLinkModel.program_id.in_(program_ids))
            .exists(),
            select(EventProgramLinkModel.event_id)
            .join(EventModel, EventModel.id == EventProgramLinkModel.event_id)
            .where(EventModel.venue_id == VenueModel.id, EventProgramLinkModel.program_id.in_(program_ids))
            .exists(),
        )

    def _apply_event_filters(self, query: Any, filters: CampusEventFilters) -> Any:
        if filters.from_date is not None:
            query = query.where(EventModel.starts_at >= filters.from_date)
        if filters.to_date is not None:
            query = query.where(EventModel.starts_at <= filters.to_date)
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

    def _to_points(self, rows: Sequence[VenueModel]) -> tuple[CampusPoint, ...]:
        if not rows:
            return ()
        point_ids = tuple(row.id for row in rows)
        links = self._load_point_links(point_ids)
        count_by_point: dict[str, int] = {}
        for count_row in self._session.execute(
            select(EventModel.venue_id, func.count(EventModel.id))
            .where(EventModel.venue_id.in_(point_ids))
            .group_by(EventModel.venue_id)
        ).all():
            point_id, count = count_row
            if point_id is not None:
                count_by_point[point_id] = int(count)
        return tuple(self._to_point(row, links.get(row.id, {}), count_by_point.get(row.id, 0)) for row in rows)

    def _to_details(self, rows: Sequence[VenueModel]) -> tuple[CampusPointDetail, ...]:
        if not rows:
            return ()
        points = self._to_points(rows)
        university_ids = tuple(sorted({value for point in points for value in point.university_ids}))
        program_ids = tuple(sorted({value for point in points for value in point.program_ids}))
        universities = {
            model.id: CampusUniversityReference.model_validate(
                {
                    "id": model.id,
                    "name": model.name,
                    "city": model.city,
                    "address": model.address,
                    "official_site": _HTTP_URL.validate_python(model.official_site),
                }
            )
            for model in self._session.scalars(select(UniversityModel).where(UniversityModel.id.in_(university_ids))).all()
        }
        programs = {
            model.id: CampusProgramReference.model_validate(
                {
                    "id": model.id,
                    "direction_id": model.direction_id,
                    "code": model.code,
                    "name": model.name,
                    "education_year": model.education_year,
                    "study_plan_url": _HTTP_URL.validate_python(model.study_plan_url),
                    "source_url": _HTTP_URL.validate_python(model.source_url),
                }
            )
            for model in self._session.scalars(select(ProgramModel).where(ProgramModel.id.in_(program_ids))).all()
        }
        result: list[CampusPointDetail] = []
        for point in points:
            result.append(
                CampusPointDetail(
                    **point.model_dump(mode="python"),
                    universities=tuple(universities[item] for item in point.university_ids),
                    departments=tuple(CampusDepartmentReference(id=item) for item in point.department_ids),
                    programs=tuple(programs[item] for item in point.program_ids),
                )
            )
        return tuple(result)

    def _load_point_links(self, point_ids: tuple[str, ...]) -> dict[str, dict[str, tuple[str, ...]]]:
        result: dict[str, dict[str, set[str]]] = {
            point_id: {"university_ids": set(), "department_ids": set(), "program_ids": set()}
            for point_id in point_ids
        }
        for model, field_name, key in (
            (VenueUniversityLinkModel, "university_id", "university_ids"),
            (VenueDepartmentLinkModel, "department_id", "department_ids"),
            (VenueProgramLinkModel, "program_id", "program_ids"),
        ):
            rows = self._session.execute(
                select(model.venue_id, getattr(model, field_name)).where(model.venue_id.in_(point_ids))
            ).all()
            for point_id, value in rows:
                result[point_id][key].add(value)
        event_link_specs: tuple[tuple[type[Any], str, str], ...] = (
            (EventUniversityLinkModel, "university_id", "university_ids"),
            (EventDepartmentLinkModel, "department_id", "department_ids"),
            (EventProgramLinkModel, "program_id", "program_ids"),
        )
        for model, field_name, key in event_link_specs:
            event_id_column = getattr(model, "event_id")
            rows = self._session.execute(
                select(EventModel.venue_id, getattr(model, field_name))
                .join(model, event_id_column == EventModel.id)
                .where(EventModel.venue_id.in_(point_ids))
            ).all()
            for point_id, value in rows:
                if point_id is not None:
                    result[point_id][key].add(value)
        return {
            point_id: {key: tuple(sorted(values)) for key, values in values_by_key.items()}
            for point_id, values_by_key in result.items()
        }

    @staticmethod
    def _to_point(row: VenueModel, links: Mapping[str, tuple[str, ...]], event_count: int) -> CampusPoint:
        primary = SourceKind(row.source_kind)
        return CampusPoint(
            id=row.id,
            point_type=CampusPointType(row.point_type),
            name=row.name,
            address=row.address,
            latitude=row.latitude,
            longitude=row.longitude,
            university_ids=links.get("university_ids", ()),
            department_ids=links.get("department_ids", ()),
            program_ids=links.get("program_ids", ()),
            event_count=event_count,
            provenance=(
                SourceAttribution(
                    kind=primary,
                    url=_HTTP_URL.validate_python(row.source_url),
                    captured_at=_aware(row.captured_at),
                    content_sha256=row.content_sha256,
                    locator=row.source_locator,
                ),
            ),
        )

    def _event_contracts(self, rows: Sequence[EventModel]) -> tuple[Event, ...]:
        if not rows:
            return ()
        from .events import SqlAlchemyEventRepository

        return SqlAlchemyEventRepository(self._session)._to_contracts(rows)

    def _validate_references(self, point: CampusPoint) -> None:
        for university_id in point.university_ids:
            if self._session.get(UniversityModel, university_id) is None:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Campus university does not exist: {university_id}")
        for program_id in point.program_ids:
            if self._session.get(ProgramModel, program_id) is None:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Campus program does not exist: {program_id}")

    def _replace_links(self, point: CampusPoint) -> None:
        self._remove_links(point.id)
        self._session.add_all(
            [VenueUniversityLinkModel(venue_id=point.id, university_id=value) for value in point.university_ids]
            + [VenueDepartmentLinkModel(venue_id=point.id, department_id=value) for value in point.department_ids]
            + [VenueProgramLinkModel(venue_id=point.id, program_id=value) for value in point.program_ids]
        )

    def _remove_links(self, point_id: str) -> int:
        removed = 0
        for model in (VenueUniversityLinkModel, VenueDepartmentLinkModel, VenueProgramLinkModel):
            result = self._session.execute(delete(model).where(model.venue_id == point_id))
            removed += int(getattr(result, "rowcount", 0) or 0)
        return removed

    def _retain_event_fallback(self, point_id: str) -> None:
        row = self._session.scalar(
            select(EventModel).where(EventModel.venue_id == point_id).order_by(EventModel.id.asc()).limit(1)
        )
        if row is None:
            return
        venue = self._session.get(VenueModel, point_id)
        if venue is None:
            return
        venue.point_type = CampusPointType.EVENT_VENUE.value
        venue.source_kind = row.source_kind
        venue.source_url = row.source_url
        venue.captured_at = row.captured_at
        venue.content_sha256 = row.content_sha256
        venue.source_locator = row.source_locator

    def _upsert(self, model: type[Any], identity: str, values: Mapping[str, object]) -> str:
        existing = self._session.get(model, identity)
        if existing is None:
            self._session.add(model(**values))
            logger.debug("campus_projection_insert model=%s identity=%s", model.__name__, identity)
            return "inserted"
        changed: list[str] = []
        for field, expected in values.items():
            if field == "id":
                continue
            actual = getattr(existing, field)
            if not _values_equal(actual, expected):
                setattr(existing, field, expected)
                changed.append(field)
        if changed:
            logger.debug("campus_projection_update model=%s identity=%s fields=%s", model.__name__, identity, ",".join(changed))
            return "updated"
        return "unchanged"


def _values_equal(actual: object, expected: object) -> bool:
    if isinstance(actual, datetime) and isinstance(expected, datetime):
        actual_utc = actual.replace(tzinfo=timezone.utc) if actual.tzinfo is None else actual.astimezone(timezone.utc)
        expected_utc = expected.replace(tzinfo=timezone.utc) if expected.tzinfo is None else expected.astimezone(timezone.utc)
        return actual_utc == expected_utc
    return actual == expected or str(actual) == str(expected)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None and value.utcoffset() is not None else value.replace(tzinfo=timezone.utc)


__all__ = ["CampusSyncStats", "SqlAlchemyCampusPointRepository"]
