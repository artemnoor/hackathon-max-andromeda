from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field, HttpUrl

from andromeda.modules.events.contracts.public import Event, EventFormat, EventKind
from andromeda.modules.events.contracts.results import EventListResult
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.ids import DepartmentId, EventId, ProgramId, UniversityId, VenueId

from .common import ApiModel


class EventProvenanceResponse(ApiModel):
    kind: SourceKind
    url: HttpUrl
    captured_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str | None = None
    university_id: str | None = None
    run_id: str | None = None
    field: str | None = None
    record_key: str | None = None
    inferred: bool = False


class VenueResponse(ApiModel):
    id: VenueId
    name: str = Field(min_length=1, max_length=512)
    address: str | None = Field(default=None, min_length=1, max_length=1024)
    latitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-90"), le=Decimal("90"), max_digits=9, decimal_places=6)
    longitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-180"), le=Decimal("180"), max_digits=9, decimal_places=6)


class EventResponse(ApiModel):
    id: EventId
    title: str = Field(min_length=1, max_length=512)
    kind: EventKind
    format: EventFormat
    starts_at: datetime
    ends_at: datetime | None = None
    description: str | None = Field(default=None, min_length=1, max_length=10_000)
    registration_url: HttpUrl | None = None
    university_ids: tuple[UniversityId, ...] = Field(min_length=1)
    department_ids: tuple[DepartmentId, ...] = ()
    program_ids: tuple[ProgramId, ...] = ()
    venue: VenueResponse | None = None
    provenance: tuple[EventProvenanceResponse, ...] = Field(min_length=1)


class EventListResponse(ApiModel):
    items: tuple[EventResponse, ...] = ()
    total: int = Field(strict=True, ge=0)


class EventDetailResponse(ApiModel):
    event: EventResponse


def event_response(event: Event) -> EventResponse:
    return EventResponse.model_validate(event.model_dump(mode="python"))


def event_list_response(result: EventListResult) -> EventListResponse:
    return EventListResponse(items=tuple(event_response(item) for item in result.items), total=result.total)


def event_detail_response(event: Event) -> EventDetailResponse:
    return EventDetailResponse(event=event_response(event))


__all__ = ["EventDetailResponse", "EventListResponse", "EventResponse", "event_detail_response", "event_list_response"]
