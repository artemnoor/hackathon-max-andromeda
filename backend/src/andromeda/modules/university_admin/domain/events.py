from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import AccountId, ProgramId, UniversityCategoryId, UniversityEventId, UniversityId, UniversityUnitId, VenueId


class EditorialEventStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class EditorialAudienceMode(StrEnum):
    ALL_UNIVERSITY = "all_university"
    SELECTED_UNITS = "selected_units"
    SELECTED_PROGRAMS = "selected_programs"
    UNAFFILIATED = "unaffiliated"


class AgendaItem(ContractModel):
    item_id: str = Field(alias="itemId", min_length=1, max_length=128)
    event_id: UniversityEventId = Field(alias="eventId")
    position: int = Field(strict=True, ge=1)
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    location_label: str | None = Field(default=None, max_length=512, alias="locationLabel")
    speaker_label: str | None = Field(default=None, max_length=512, alias="speakerLabel")
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_window(self) -> AgendaItem:
        for name, value in (("starts_at", self.starts_at), ("ends_at", self.ends_at)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"agenda {name} must be timezone-aware")
        if self.starts_at is not None and self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("agenda ends_at must be after starts_at")
        return self


class EditorialEvent(ContractModel):
    event_id: UniversityEventId = Field(alias="eventId")
    university_id: UniversityId = Field(alias="universityId")
    slug: str = Field(min_length=1, max_length=96)
    title: str = Field(min_length=1, max_length=512)
    kind: EventKind
    format: EventFormat
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    description: str | None = Field(default=None, max_length=10000)
    registration_url: str | None = Field(default=None, max_length=2048, alias="registrationUrl")
    venue_id: VenueId | None = Field(default=None, alias="venueId")
    location_label: str | None = Field(default=None, max_length=512, alias="locationLabel")
    location_address: str | None = Field(default=None, max_length=1024, alias="locationAddress")
    online_url: str | None = Field(default=None, max_length=2048, alias="onlineUrl")
    status: EditorialEventStatus
    audience_mode: EditorialAudienceMode = Field(alias="audienceMode")
    revision: int = Field(ge=1)
    created_by_account_id: AccountId = Field(alias="createdByAccountId")
    updated_by_account_id: AccountId = Field(alias="updatedByAccountId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    archived_at: datetime | None = Field(default=None, alias="archivedAt")

    @model_validator(mode="after")
    def validate_time(self) -> EditorialEvent:
        for name, value in (("starts_at", self.starts_at), ("ends_at", self.ends_at), ("created_at", self.created_at), ("updated_at", self.updated_at), ("published_at", self.published_at), ("archived_at", self.archived_at)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"event {name} must be timezone-aware")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("event ends_at must be after starts_at")
        return self


class EditorialEventRelations(ContractModel):
    event_id: UniversityEventId = Field(alias="eventId")
    unit_ids: tuple[UniversityUnitId, ...] = Field(default=(), alias="unitIds")
    program_ids: tuple[ProgramId, ...] = Field(default=(), alias="programIds")
    category_ids: tuple[UniversityCategoryId, ...] = Field(default=(), alias="categoryIds")


class EditorialEventSnapshot(ContractModel):
    event: EditorialEvent
    relations: EditorialEventRelations
    agenda: tuple[AgendaItem, ...] = ()


__all__ = ["AgendaItem", "EditorialAudienceMode", "EditorialEvent", "EditorialEventRelations", "EditorialEventSnapshot", "EditorialEventStatus"]
