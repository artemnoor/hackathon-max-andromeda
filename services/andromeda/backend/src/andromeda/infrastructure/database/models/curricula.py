from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class AssessmentTypeModel(Base):
    __tablename__ = "assessment_types"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)


class CurriculumModel(Base):
    __tablename__ = "curricula"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    program_id: Mapped[str] = mapped_column(ForeignKey("educational_programs.id"), nullable=False)
    education_year: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    source_gaps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")

    __table_args__ = (
        UniqueConstraint("program_id", "education_year", name="uq_curriculum_program_year"),
        CheckConstraint("education_year >= 2000 AND education_year <= 2100", name="ck_curriculum_education_year"),
        CheckConstraint("id LIKE 'curriculum:%'", name="ck_curriculum_id_shape"),
    )


class CurriculumItemModel(Base):
    __tablename__ = "curriculum_items"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    curriculum_id: Mapped[str] = mapped_column(ForeignKey("curricula.id"), nullable=False)
    discipline_id: Mapped[str] = mapped_column(ForeignKey("disciplines.id"), nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester_identity: Mapped[str] = mapped_column(String(16), nullable=False)
    hours: Mapped[int] = mapped_column(Integer, nullable=False)
    credits: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    source_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lecture_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    practice_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lab_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    self_study_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_elective: Mapped[bool | None] = mapped_column(nullable=True)
    course_block: Mapped[str | None] = mapped_column(String(128), nullable=True)
    practice_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        UniqueConstraint("curriculum_id", "discipline_id", "semester_identity", name="uq_curriculum_item_identity"),
        CheckConstraint("semester IS NULL OR (semester >= 1 AND semester <= 12)", name="ck_item_semester"),
        CheckConstraint("semester_identity = 'unassigned' OR semester_identity LIKE 'legacy:%' OR semester_identity = 'semester:' || semester", name="ck_item_semester_identity"),
        CheckConstraint("hours >= 0 AND hours <= 2000", name="ck_item_hours"),
        CheckConstraint("credits IS NULL OR (credits >= 0 AND credits <= 60)", name="ck_item_credits"),
        CheckConstraint("length(source_name) > 0", name="ck_item_source_name_non_empty"),
        CheckConstraint("source_position IS NULL OR source_position >= 1", name="ck_item_source_position"),
        CheckConstraint("lecture_hours IS NULL OR (lecture_hours >= 0 AND lecture_hours <= 2000)", name="ck_item_lecture_hours"),
        CheckConstraint("practice_hours IS NULL OR (practice_hours >= 0 AND practice_hours <= 2000)", name="ck_item_practice_hours"),
        CheckConstraint("lab_hours IS NULL OR (lab_hours >= 0 AND lab_hours <= 2000)", name="ck_item_lab_hours"),
        CheckConstraint("self_study_hours IS NULL OR (self_study_hours >= 0 AND self_study_hours <= 2000)", name="ck_item_self_study_hours"),
    )


class CurriculumItemAssessmentModel(Base):
    __tablename__ = "curriculum_item_assessments"

    curriculum_item_id: Mapped[str] = mapped_column(ForeignKey("curriculum_items.id", ondelete="CASCADE"), primary_key=True)
    assessment_type_id: Mapped[str] = mapped_column(ForeignKey("assessment_types.id"), primary_key=True)


class CurriculumItemSourceLinkModel(Base):
    __tablename__ = "curriculum_item_source_links"

    link_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    curriculum_item_id: Mapped[str] = mapped_column(ForeignKey("curriculum_items.id", ondelete="CASCADE"), nullable=False)
    source_sha256: Mapped[str] = mapped_column(ForeignKey("source_snapshots.content_sha256"), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    university_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ingest_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "curriculum_item_id",
            "source_sha256",
            "source_url",
            "locator",
            "field",
            "record_key",
            name="uq_curriculum_item_source_link",
        ),
        Index("ix_curriculum_item_source_links_item", "curriculum_item_id"),
        Index("ix_curriculum_item_source_links_source", "source_sha256"),
    )
