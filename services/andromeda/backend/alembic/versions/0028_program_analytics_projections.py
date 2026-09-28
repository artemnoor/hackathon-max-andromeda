"""Persist rebuildable program analytical projections and metric evidence."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0028_prog_proj"
down_revision = "0027_sem_enrich"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program_projections",
        sa.Column("program_id", sa.String(length=96), sa.ForeignKey("educational_programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("university_id", sa.String(length=64), sa.ForeignKey("universities.id"), nullable=False),
        sa.Column("direction_id", sa.String(length=64), sa.ForeignKey("directions.id"), nullable=False),
        sa.Column("program_code", sa.String(length=24), nullable=False),
        sa.Column("program_name", sa.String(length=512), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("basis", sa.String(length=32), nullable=False),
        sa.Column("total_hours", sa.Integer(), nullable=True),
        sa.Column("total_credits", sa.Numeric(10, 2), nullable=True),
        sa.Column("total_workload", sa.Numeric(12, 2), nullable=True),
        sa.Column("academic_areas_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("timeline_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("activity_signals_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("assessment_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("admission_offerings_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("distinctive_subjects_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("coverage", sa.Numeric(5, 4), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("freshness_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("semantic_version", sa.String(length=64), nullable=True),
        sa.Column("classifier_version", sa.String(length=64), nullable=True),
        sa.Column("ingest_run_id", sa.String(length=64), sa.ForeignKey("ingest_runs.id"), nullable=True),
        sa.Column("provenance_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_gaps_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("program_id"),
        sa.CheckConstraint("basis IN ('hours', 'credits', 'course_count', 'normalized_workload')", name="ck_program_projection_basis"),
        sa.CheckConstraint("quality_status IN ('available', 'partial', 'insufficient_data', 'unavailable')", name="ck_program_projection_quality"),
        sa.CheckConstraint("coverage >= 0 AND coverage <= 1", name="ck_program_projection_coverage"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_program_projection_confidence"),
    )
    op.create_index("ix_program_projections_university_direction", "program_projections", ["university_id", "direction_id"])
    op.create_index("ix_program_projections_quality_version", "program_projections", ["quality_status", "schema_version"])
    op.create_index("ix_program_projections_ingest", "program_projections", ["ingest_run_id"])

    op.create_table(
        "program_metrics",
        sa.Column("program_id", sa.String(length=96), sa.ForeignKey("program_projections.program_id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_code", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Numeric(12, 6), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("basis", sa.String(length=32), nullable=True),
        sa.Column("coverage", sa.Numeric(5, 4), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("semantic_version", sa.String(length=64), nullable=True),
        sa.Column("classifier_version", sa.String(length=64), nullable=True),
        sa.Column("provenance_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_gaps_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("program_id", "metric_code", "schema_version"),
        sa.CheckConstraint("value IS NULL OR value >= 0", name="ck_program_metric_value_nonnegative"),
        sa.CheckConstraint("status IN ('available', 'partial', 'insufficient_data', 'unavailable')", name="ck_program_metric_quality"),
        sa.CheckConstraint("coverage >= 0 AND coverage <= 1", name="ck_program_metric_coverage"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_program_metric_confidence"),
        sa.CheckConstraint("(status = 'available' AND value IS NOT NULL) OR status <> 'available'", name="ck_program_metric_status_value"),
    )
    op.create_index("ix_program_metrics_code_value", "program_metrics", ["metric_code", "value"])
    op.create_index("ix_program_metrics_status_version", "program_metrics", ["status", "schema_version"])

    op.create_table(
        "program_metric_evidence",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("program_id", sa.String(length=96), sa.ForeignKey("program_projections.program_id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_code", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("curriculum_item_id", sa.String(length=256), sa.ForeignKey("curriculum_items.id", ondelete="CASCADE"), nullable=True),
        sa.Column("feature_id", sa.String(length=96), nullable=True),
        sa.Column("contribution", sa.Numeric(12, 6), nullable=True),
        sa.Column("source_hash", sa.String(length=64), sa.ForeignKey("source_snapshots.content_sha256"), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("provenance_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_program_metric_evidence_program_metric", "program_metric_evidence", ["program_id", "metric_code", "schema_version"])
    op.create_index("ix_program_metric_evidence_item", "program_metric_evidence", ["curriculum_item_id"])


def downgrade() -> None:
    op.drop_index("ix_program_metric_evidence_item", table_name="program_metric_evidence")
    op.drop_index("ix_program_metric_evidence_program_metric", table_name="program_metric_evidence")
    op.drop_table("program_metric_evidence")
    op.drop_index("ix_program_metrics_status_version", table_name="program_metrics")
    op.drop_index("ix_program_metrics_code_value", table_name="program_metrics")
    op.drop_table("program_metrics")
    op.drop_index("ix_program_projections_ingest", table_name="program_projections")
    op.drop_index("ix_program_projections_quality_version", table_name="program_projections")
    op.drop_index("ix_program_projections_university_direction", table_name="program_projections")
    op.drop_table("program_projections")
