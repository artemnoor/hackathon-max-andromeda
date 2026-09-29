from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class AdmissionCycleModel(Base):
    __tablename__ = "admission_cycles"

    cycle_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id", ondelete="RESTRICT"), nullable=False)
    admission_year: Mapped[int] = mapped_column(Integer, nullable=False)
    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)
    application_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    application_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    enrollment_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    enrollment_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_by_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approval_reason: Mapped[str] = mapped_column(String(512), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "university_id",
            "admission_year",
            "revision",
            name="uq_admission_cycle_university_year_revision",
        ),
        CheckConstraint("cycle_id LIKE 'admission-cycle:%'", name="ck_admission_cycle_id_prefix"),
        CheckConstraint(
            "cycle_id = 'admission-cycle:' || replace(university_id, 'university:', '') || ':' || admission_year",
            name="ck_admission_cycle_id_matches_natural_key",
        ),
        CheckConstraint(
            "admission_year BETWEEN 2000 AND 2100", name="ck_admission_cycle_admission_year"
        ),
        CheckConstraint(
            "length(academic_year) = 9 AND substr(academic_year, 5, 1) = '/' "
            "AND CAST(substr(academic_year, 6, 4) AS INTEGER) = CAST(substr(academic_year, 1, 4) AS INTEGER) + 1",
            name="ck_admission_cycle_academic_year",
        ),
        CheckConstraint("revision >= 1", name="ck_admission_cycle_revision"),
        CheckConstraint("recorded_at >= approved_at", name="ck_admission_cycle_recorded_after_approval"),
        CheckConstraint(
            "state IN ('planned', 'published', 'application_open', 'enrollment_open', 'closed', 'cancelled', 'unknown')",
            name="ck_admission_cycle_state",
        ),
        CheckConstraint(
            "(application_start IS NULL AND application_end IS NULL) OR "
            "(application_start IS NOT NULL AND application_end IS NOT NULL AND application_start <= application_end)",
            name="ck_admission_cycle_application_period",
        ),
        CheckConstraint(
            "(enrollment_start IS NULL AND enrollment_end IS NULL) OR "
            "(enrollment_start IS NOT NULL AND enrollment_end IS NOT NULL AND enrollment_start <= enrollment_end)",
            name="ck_admission_cycle_enrollment_period",
        ),
        CheckConstraint("length(approval_reason) > 0", name="ck_admission_cycle_approval_reason"),
        Index("ix_admission_cycle_as_known", "university_id", "admission_year", "recorded_at"),
    )


class AdmissionCycleEvidenceModel(Base):
    __tablename__ = "admission_cycle_evidence"

    cycle_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    cycle_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_observation_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_source_observations.source_observation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    locator_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_table: Mapped[str | None] = mapped_column(String(256), nullable=True)
    locator_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_section: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locator_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locator_record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(nullable=False, default=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["cycle_id", "cycle_revision"],
            ["admission_cycles.cycle_id", "admission_cycles.revision"],
            ondelete="RESTRICT",
            name="fk_admission_cycle_evidence_revision",
        ),
        CheckConstraint("ordinal >= 0", name="ck_admission_cycle_evidence_ordinal"),
        CheckConstraint("length(source_url) > 0", name="ck_admission_cycle_evidence_url"),
        CheckConstraint("locator_page IS NULL OR locator_page >= 1", name="ck_admission_cycle_evidence_page"),
        CheckConstraint("locator_row IS NULL OR locator_row >= 1", name="ck_admission_cycle_evidence_row"),
        Index("ix_admission_cycle_evidence_observation", "source_observation_id"),
    )


__all__ = ["AdmissionCycleEvidenceModel", "AdmissionCycleModel"]
