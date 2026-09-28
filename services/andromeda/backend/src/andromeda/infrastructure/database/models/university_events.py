from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class UniversityEditorialEventModel(Base):
    __tablename__ = "university_editorial_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(96), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_id: Mapped[str | None] = mapped_column(ForeignKey("venues.id"), nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    location_address: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    online_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    audience_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    updated_by_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("university_id", "slug", name="uq_university_editorial_event_slug"),
        CheckConstraint("event_id LIKE 'university-event:%:%'", name="ck_university_editorial_event_id"),
        CheckConstraint("kind IN ('additional_education', 'open_day', 'lecture', 'competition', 'career', 'other')", name="ck_university_editorial_event_kind"),
        CheckConstraint("format IN ('offline', 'online', 'hybrid')", name="ck_university_editorial_event_format"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_university_editorial_event_status"),
        CheckConstraint("audience_mode IN ('all_university', 'selected_units', 'selected_programs', 'unaffiliated')", name="ck_university_editorial_event_audience"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_university_editorial_event_time_window"),
        CheckConstraint("revision >= 1", name="ck_university_editorial_event_revision"),
        CheckConstraint("length(title) > 0 AND length(slug) > 0", name="ck_university_editorial_event_text"),
        Index("ix_university_editorial_events_public", "university_id", "status", "starts_at"),
    )


class UniversityEditorialAgendaItemModel(Base):
    __tablename__ = "university_editorial_agenda_items"

    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("university_editorial_events.event_id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    speaker_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        UniqueConstraint("event_id", "position", name="uq_university_editorial_agenda_position"),
        CheckConstraint("position >= 1", name="ck_university_editorial_agenda_position"),
        CheckConstraint("ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="ck_university_editorial_agenda_time_window"),
        CheckConstraint("length(title) > 0", name="ck_university_editorial_agenda_title"),
    )


class UniversityEditorialEventUnitLinkModel(Base):
    __tablename__ = "university_editorial_event_unit_links"

    event_id: Mapped[str] = mapped_column(ForeignKey("university_editorial_events.event_id", ondelete="CASCADE"), primary_key=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("university_units.unit_id"), primary_key=True)

    __table_args__ = (Index("ix_university_editorial_event_unit_links_unit_id", "unit_id"),)


class UniversityEditorialEventProgramLinkModel(Base):
    __tablename__ = "university_editorial_event_program_links"

    event_id: Mapped[str] = mapped_column(ForeignKey("university_editorial_events.event_id", ondelete="CASCADE"), primary_key=True)
    program_id: Mapped[str] = mapped_column(String(96), primary_key=True)

    __table_args__ = (Index("ix_university_editorial_event_program_links_program_id", "program_id"),)


class UniversityEditorialEventCategoryLinkModel(Base):
    __tablename__ = "university_editorial_event_category_links"

    event_id: Mapped[str] = mapped_column(ForeignKey("university_editorial_events.event_id", ondelete="CASCADE"), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("university_categories.category_id"), primary_key=True)

    __table_args__ = (Index("ix_university_editorial_event_category_links_category_id", "category_id"),)


__all__ = [
    "UniversityEditorialAgendaItemModel",
    "UniversityEditorialEventCategoryLinkModel",
    "UniversityEditorialEventModel",
    "UniversityEditorialEventProgramLinkModel",
    "UniversityEditorialEventUnitLinkModel",
]
