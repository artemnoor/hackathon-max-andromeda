from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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


class ProgramProjectionModel(Base):
    """Materialized, rebuildable analytical view of a canonical program."""

    __tablename__ = "program_projections"

    program_id: Mapped[str] = mapped_column(ForeignKey("educational_programs.id", ondelete="CASCADE"), primary_key=True)
    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), nullable=False)
    direction_id: Mapped[str] = mapped_column(ForeignKey("directions.id"), nullable=False)
    program_code: Mapped[str] = mapped_column(String(24), nullable=False)
    program_name: Mapped[str] = mapped_column(String(512), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    basis: Mapped[str] = mapped_column(String(32), nullable=False)
    total_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_credits: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    total_workload: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    academic_areas_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    timeline_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    activity_signals_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    assessment_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    admission_offerings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    distinctive_subjects_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False)
    coverage: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    semantic_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classifier_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingest_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_runs.id"), nullable=True)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    source_gaps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    projection_run_id: Mapped[str | None] = mapped_column(ForeignKey("program_projection_runs.id", ondelete="SET NULL"), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    materialization_status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")

    __table_args__ = (
        CheckConstraint("basis IN ('hours', 'credits', 'course_count', 'normalized_workload')", name="ck_program_projection_basis"),
        CheckConstraint("quality_status IN ('available', 'partial', 'insufficient_data', 'unavailable')", name="ck_program_projection_quality"),
        CheckConstraint("coverage >= 0 AND coverage <= 1", name="ck_program_projection_coverage"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_program_projection_confidence"),
        CheckConstraint("materialization_status IN ('active', 'stale', 'failed')", name="ck_program_projection_materialization_status"),
        Index("ix_program_projections_university_direction", "university_id", "direction_id"),
        Index("ix_program_projections_quality_version", "quality_status", "schema_version"),
        Index("ix_program_projections_ingest", "ingest_run_id"),
        Index("ix_program_projections_materialization", "materialization_status", "schema_version"),
    )


class ProgramMetricModel(Base):
    __tablename__ = "program_metrics"

    program_id: Mapped[str] = mapped_column(ForeignKey("program_projections.program_id", ondelete="CASCADE"), primary_key=True)
    metric_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    basis: Mapped[str | None] = mapped_column(String(32), nullable=True)
    coverage: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    semantic_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classifier_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    source_gaps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("value IS NULL OR value >= 0", name="ck_program_metric_value_nonnegative"),
        CheckConstraint("status IN ('available', 'partial', 'insufficient_data', 'unavailable')", name="ck_program_metric_quality"),
        CheckConstraint("coverage >= 0 AND coverage <= 1", name="ck_program_metric_coverage"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_program_metric_confidence"),
        CheckConstraint("(status = 'available' AND value IS NOT NULL) OR status <> 'available'", name="ck_program_metric_status_value"),
        Index("ix_program_metrics_code_value", "metric_code", "value"),
        Index("ix_program_metrics_status_version", "status", "schema_version"),
    )


class ProgramMetricEvidenceModel(Base):
    __tablename__ = "program_metric_evidence"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    program_id: Mapped[str] = mapped_column(ForeignKey("program_projections.program_id", ondelete="CASCADE"), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    curriculum_item_id: Mapped[str | None] = mapped_column(ForeignKey("curriculum_items.id", ondelete="CASCADE"), nullable=True)
    feature_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    contribution: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(ForeignKey("source_snapshots.content_sha256"), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")

    __table_args__ = (
        Index("ix_program_metric_evidence_program_metric", "program_id", "metric_code", "schema_version"),
        Index("ix_program_metric_evidence_item", "curriculum_item_id"),
    )


__all__ = ["ProgramMetricEvidenceModel", "ProgramMetricModel", "ProgramProjectionModel"]


class ProgramProjectionRunModel(Base):
    __tablename__ = "program_projection_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    ingest_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_runs.id"), nullable=True)
    university_id: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classifier_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    affected_program_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    refreshed_program_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'partial', 'failed')", name="ck_projection_run_status"),
        CheckConstraint("affected_program_count >= 0", name="ck_projection_run_affected_count"),
        CheckConstraint("refreshed_program_count >= 0", name="ck_projection_run_refreshed_count"),
        Index("ix_projection_runs_status_started", "status", "started_at"),
        Index("ix_projection_runs_ingest", "ingest_run_id"),
        UniqueConstraint("university_id", "projection_version", "input_hash", name="uq_projection_run_target"),
    )
