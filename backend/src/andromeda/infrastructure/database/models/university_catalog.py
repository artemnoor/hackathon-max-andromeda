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


class UniversityUnitModel(Base):
    __tablename__ = "university_units"

    unit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_unit_id: Mapped[str | None] = mapped_column(ForeignKey("university_units.unit_id"), nullable=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    updated_by_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("university_id", "slug", name="uq_university_unit_slug"),
        CheckConstraint("unit_id LIKE 'unit:%:%'", name="ck_university_unit_id"),
        CheckConstraint("unit_type IN ('faculty', 'department')", name="ck_university_unit_type"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_university_unit_status"),
        CheckConstraint("sort_order >= 0", name="ck_university_unit_sort_order"),
        CheckConstraint("revision >= 1", name="ck_university_unit_revision"),
        CheckConstraint("length(slug) > 0", name="ck_university_unit_slug"),
        CheckConstraint("length(name) > 0", name="ck_university_unit_name"),
        Index("ix_university_units_public", "university_id", "status", "sort_order"),
    )


class UniversityCategoryModel(Base):
    __tablename__ = "university_categories"

    category_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    updated_by_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("university_id", "slug", name="uq_university_category_slug"),
        CheckConstraint("category_id LIKE 'category:%:%'", name="ck_university_category_id"),
        CheckConstraint("category_kind IN ('subject', 'program', 'event', 'general')", name="ck_university_category_kind"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_university_category_status"),
        CheckConstraint("sort_order >= 0", name="ck_university_category_sort_order"),
        CheckConstraint("revision >= 1", name="ck_university_category_revision"),
        CheckConstraint("length(slug) > 0", name="ck_university_category_slug"),
        CheckConstraint("length(name) > 0", name="ck_university_category_name"),
        Index("ix_university_categories_public", "university_id", "status", "sort_order"),
    )


class UniversityProgramEditorialModel(Base):
    __tablename__ = "university_program_editorials"

    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), primary_key=True)
    program_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    public_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="visible", server_default="visible")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("visibility IN ('visible', 'hidden')", name="ck_university_program_editorial_visibility"),
        CheckConstraint("revision >= 1", name="ck_university_program_editorial_revision"),
    )


class UniversityDisciplineEditorialModel(Base):
    __tablename__ = "university_discipline_editorials"

    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), primary_key=True)
    discipline_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    public_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="visible", server_default="visible")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("visibility IN ('visible', 'hidden')", name="ck_university_discipline_editorial_visibility"),
        CheckConstraint("revision >= 1", name="ck_university_discipline_editorial_revision"),
    )


class UniversityCategoryProgramLinkModel(Base):
    __tablename__ = "university_category_program_links"

    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("university_categories.category_id"), primary_key=True)
    program_id: Mapped[str] = mapped_column(String(96), primary_key=True)

    __table_args__ = (Index("ix_university_category_program_links_university_id", "university_id"),)


class UniversityCategoryDisciplineLinkModel(Base):
    __tablename__ = "university_category_discipline_links"

    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("university_categories.category_id"), primary_key=True)
    discipline_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    __table_args__ = (Index("ix_university_category_discipline_links_university_id", "university_id"),)


class UniversityUnitProgramLinkModel(Base):
    __tablename__ = "university_unit_program_links"

    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), primary_key=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("university_units.unit_id"), primary_key=True)
    program_id: Mapped[str] = mapped_column(String(96), primary_key=True)

    __table_args__ = (Index("ix_university_unit_program_links_university_id", "university_id"),)


class UniversityUnitDisciplineLinkModel(Base):
    __tablename__ = "university_unit_discipline_links"

    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), primary_key=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey("university_units.unit_id"), primary_key=True)
    discipline_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    __table_args__ = (Index("ix_university_unit_discipline_links_university_id", "university_id"),)


__all__ = [
    "UniversityCategoryDisciplineLinkModel",
    "UniversityCategoryModel",
    "UniversityCategoryProgramLinkModel",
    "UniversityDisciplineEditorialModel",
    "UniversityProgramEditorialModel",
    "UniversityUnitDisciplineLinkModel",
    "UniversityUnitModel",
    "UniversityUnitProgramLinkModel",
]
