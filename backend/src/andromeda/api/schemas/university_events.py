from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, TypeVar

from pydantic import BeforeValidator, Field, model_validator

from andromeda.api.schemas.common import ApiModel
from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.modules.university_admin.contracts.events import AgendaItem, EditorialAudienceMode, EditorialEvent, EditorialEventRelations, EditorialEventSnapshot, EditorialEventStatus
from andromeda.shared.contracts.ids import DisciplineId, ProgramId, UniversityCategoryId, UniversityEventId, UniversityId, UniversityUnitId, VenueId


EnumT = TypeVar("EnumT", bound=Enum)


def _enum_from_json(enum_type: type[EnumT], value: object) -> EnumT:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        return enum_type(value)
    raise TypeError(f"{enum_type.__name__} must be a string")


def _datetime_from_json(value: object) -> object:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _sequence_from_json(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return value


JsonDateTime = Annotated[datetime, BeforeValidator(_datetime_from_json)]
JsonEventKind = Annotated[EventKind, BeforeValidator(lambda value: _enum_from_json(EventKind, value))]
JsonEventFormat = Annotated[EventFormat, BeforeValidator(lambda value: _enum_from_json(EventFormat, value))]
JsonAudienceMode = Annotated[EditorialAudienceMode, BeforeValidator(lambda value: _enum_from_json(EditorialAudienceMode, value))]
JsonEventStatus = Annotated[EditorialEventStatus, BeforeValidator(lambda value: _enum_from_json(EditorialEventStatus, value))]
JsonUnitIds = Annotated[tuple[UniversityUnitId, ...], BeforeValidator(_sequence_from_json)]
JsonProgramIds = Annotated[tuple[ProgramId, ...], BeforeValidator(_sequence_from_json)]
JsonCategoryIds = Annotated[tuple[UniversityCategoryId, ...], BeforeValidator(_sequence_from_json)]


class AgendaItemRequest(ApiModel):
    item_id: str = Field(alias="itemId", min_length=1, max_length=128)
    position: int = Field(strict=True, ge=1)
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: JsonDateTime | None = Field(default=None, alias="startsAt")
    ends_at: JsonDateTime | None = Field(default=None, alias="endsAt")
    location_label: str | None = Field(default=None, max_length=512, alias="locationLabel")
    speaker_label: str | None = Field(default=None, max_length=512, alias="speakerLabel")

    @model_validator(mode="after")
    def validate_timezone(self) -> "AgendaItemRequest":
        for name, value in (("starts_at", self.starts_at), ("ends_at", self.ends_at)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"agenda {name} must be timezone-aware")
        if self.starts_at is not None and self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("agenda ends_at must be after starts_at")
        return self


JsonAgendaItems = Annotated[tuple[AgendaItemRequest, ...], BeforeValidator(_sequence_from_json)]


class UniversityEditorialEventRequest(ApiModel):
    slug: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1, max_length=512)
    kind: JsonEventKind
    format: JsonEventFormat
    starts_at: JsonDateTime = Field(alias="startsAt")
    ends_at: JsonDateTime | None = Field(default=None, alias="endsAt")
    description: str | None = Field(default=None, max_length=10000)
    registration_url: str | None = Field(default=None, max_length=2048, alias="registrationUrl")
    venue_id: VenueId | None = Field(default=None, alias="venueId")
    location_label: str | None = Field(default=None, max_length=512, alias="locationLabel")
    location_address: str | None = Field(default=None, max_length=1024, alias="locationAddress")
    online_url: str | None = Field(default=None, max_length=2048, alias="onlineUrl")
    audience_mode: JsonAudienceMode = Field(alias="audienceMode")
    unit_ids: JsonUnitIds = Field(default=(), alias="unitIds")
    program_ids: JsonProgramIds = Field(default=(), alias="programIds")
    category_ids: JsonCategoryIds = Field(default=(), alias="categoryIds")
    agenda: JsonAgendaItems = ()

    @model_validator(mode="after")
    def validate_timezone(self) -> "UniversityEditorialEventRequest":
        for name, value in (("starts_at", self.starts_at), ("ends_at", self.ends_at)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"event {name} must be timezone-aware")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("event ends_at must be after starts_at")
        return self


class UniversityEditorialEventUpdateRequest(UniversityEditorialEventRequest):
    expected_revision: int = Field(strict=True, ge=1, alias="expectedRevision")


class AgendaReplaceRequest(ApiModel):
    expected_revision: int = Field(strict=True, ge=1, alias="expectedRevision")
    agenda: JsonAgendaItems = ()


class EventTargetResponse(ApiModel):
    id: str
    name: str


class AgendaItemAdminResponse(ApiModel):
    item_id: str = Field(alias="itemId")
    position: int
    title: str
    description: str | None = None
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    location_label: str | None = Field(default=None, alias="locationLabel")
    speaker_label: str | None = Field(default=None, alias="speakerLabel")
    revision: int


class AgendaItemPublicResponse(ApiModel):
    item_id: str = Field(alias="itemId")
    position: int
    title: str
    description: str | None = None
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    location_label: str | None = Field(default=None, alias="locationLabel")
    speaker_label: str | None = Field(default=None, alias="speakerLabel")


class UniversityEditorialEventAdminResponse(ApiModel):
    event_id: UniversityEventId = Field(alias="eventId")
    university_id: UniversityId = Field(alias="universityId")
    slug: str
    title: str
    kind: EventKind
    format: EventFormat
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    description: str | None = None
    registration_url: str | None = Field(default=None, alias="registrationUrl")
    venue_id: str | None = Field(default=None, alias="venueId")
    location_label: str | None = Field(default=None, alias="locationLabel")
    location_address: str | None = Field(default=None, alias="locationAddress")
    online_url: str | None = Field(default=None, alias="onlineUrl")
    status: EditorialEventStatus
    audience_mode: EditorialAudienceMode = Field(alias="audienceMode")
    revision: int
    origin: Literal["university_editorial"] = "university_editorial"
    units: tuple[EventTargetResponse, ...] = ()
    programs: tuple[EventTargetResponse, ...] = ()
    categories: tuple[EventTargetResponse, ...] = ()
    agenda: tuple[AgendaItemAdminResponse, ...] = ()


class UniversityEditorialEventPublicResponse(ApiModel):
    event_id: UniversityEventId = Field(alias="eventId")
    university_id: UniversityId = Field(alias="universityId")
    slug: str
    title: str
    kind: EventKind
    format: EventFormat
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    description: str | None = None
    registration_url: str | None = Field(default=None, alias="registrationUrl")
    venue_id: str | None = Field(default=None, alias="venueId")
    location_label: str | None = Field(default=None, alias="locationLabel")
    location_address: str | None = Field(default=None, alias="locationAddress")
    online_url: str | None = Field(default=None, alias="onlineUrl")
    audience_mode: EditorialAudienceMode = Field(alias="audienceMode")
    origin: Literal["university_editorial"] = "university_editorial"
    units: tuple[EventTargetResponse, ...] = ()
    programs: tuple[EventTargetResponse, ...] = ()
    categories: tuple[EventTargetResponse, ...] = ()
    agenda: tuple[AgendaItemPublicResponse, ...] = ()


class UniversityEditorialEventAdminListResponse(ApiModel):
    items: tuple[UniversityEditorialEventAdminResponse, ...] = ()
    total: int = Field(strict=True, ge=0)


class UniversityEditorialEventPublicListResponse(ApiModel):
    items: tuple[UniversityEditorialEventPublicResponse, ...] = ()
    total: int = Field(strict=True, ge=0)


class UniversityEditorialEventAdminDetailResponse(ApiModel):
    event: UniversityEditorialEventAdminResponse


class UniversityEditorialEventPublicDetailResponse(ApiModel):
    event: UniversityEditorialEventPublicResponse


def _targets(ids: tuple[str, ...], labels: dict[str, str]) -> tuple[EventTargetResponse, ...]:
    return tuple(EventTargetResponse(id=item, name=labels.get(item, item)) for item in ids)


def admin_event_response(snapshot: EditorialEventSnapshot, labels: dict[str, str]) -> UniversityEditorialEventAdminResponse:
    event = snapshot.event
    return UniversityEditorialEventAdminResponse(
        eventId=event.event_id,
        universityId=event.university_id,
        slug=event.slug,
        title=event.title,
        kind=event.kind,
        format=event.format,
        startsAt=event.starts_at,
        endsAt=event.ends_at,
        description=event.description,
        registrationUrl=event.registration_url,
        venueId=event.venue_id,
        locationLabel=event.location_label,
        locationAddress=event.location_address,
        onlineUrl=event.online_url,
        status=event.status,
        audienceMode=event.audience_mode,
        revision=event.revision,
        units=_targets(snapshot.relations.unit_ids, labels),
        programs=_targets(snapshot.relations.program_ids, labels),
        categories=_targets(snapshot.relations.category_ids, labels),
        agenda=tuple(
            AgendaItemAdminResponse(
                itemId=item.item_id,
                position=item.position,
                title=item.title,
                description=item.description,
                startsAt=item.starts_at,
                endsAt=item.ends_at,
                locationLabel=item.location_label,
                speakerLabel=item.speaker_label,
                revision=item.revision,
            )
            for item in snapshot.agenda
        ),
    )


def public_event_response(snapshot: EditorialEventSnapshot, labels: dict[str, str]) -> UniversityEditorialEventPublicResponse:
    event = snapshot.event
    return UniversityEditorialEventPublicResponse(
        eventId=event.event_id,
        universityId=event.university_id,
        slug=event.slug,
        title=event.title,
        kind=event.kind,
        format=event.format,
        startsAt=event.starts_at,
        endsAt=event.ends_at,
        description=event.description,
        registrationUrl=event.registration_url,
        venueId=event.venue_id,
        locationLabel=event.location_label,
        locationAddress=event.location_address,
        onlineUrl=event.online_url,
        audienceMode=event.audience_mode,
        units=_targets(snapshot.relations.unit_ids, labels),
        programs=_targets(snapshot.relations.program_ids, labels),
        categories=_targets(snapshot.relations.category_ids, labels),
        agenda=tuple(
            AgendaItemPublicResponse(
                itemId=item.item_id,
                position=item.position,
                title=item.title,
                description=item.description,
                startsAt=item.starts_at,
                endsAt=item.ends_at,
                locationLabel=item.location_label,
                speakerLabel=item.speaker_label,
            )
            for item in snapshot.agenda
        ),
    )


__all__ = [
    "AgendaReplaceRequest",
    "AgendaItemRequest",
    "UniversityEditorialEventAdminDetailResponse",
    "UniversityEditorialEventAdminListResponse",
    "UniversityEditorialEventAdminResponse",
    "UniversityEditorialEventPublicDetailResponse",
    "UniversityEditorialEventPublicListResponse",
    "UniversityEditorialEventPublicResponse",
    "UniversityEditorialEventRequest",
    "UniversityEditorialEventUpdateRequest",
    "admin_event_response",
    "public_event_response",
]
