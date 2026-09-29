"""Persist admission-benefit source coverage for each ingestion run."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0036_admission_benefit_coverage"
down_revision = "0035_benefit_team_member"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "admission_benefit_ingestion_coverage",
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("source_run_id", sa.String(length=64), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("documents_discovered", sa.Integer(), nullable=False),
        sa.Column("documents_selected", sa.Integer(), nullable=False),
        sa.Column("documents_captured", sa.Integer(), nullable=False),
        sa.Column("documents_parsed", sa.Integer(), nullable=False),
        sa.Column("required_documents_expected", sa.Integer(), nullable=False),
        sa.Column("required_documents_discovered", sa.Integer(), nullable=False),
        sa.Column("required_documents_captured", sa.Integer(), nullable=False),
        sa.Column("records_normalized", sa.Integer(), nullable=False),
        sa.Column("targets_resolved", sa.Integer(), nullable=False),
        sa.Column("unresolved_targets", sa.Integer(), nullable=False),
        sa.Column("conflicts", sa.Integer(), nullable=False),
        sa.Column("review_required_rows", sa.Integer(), nullable=False),
        sa.Column("source_hashes_json", _JSON, nullable=False),
        sa.Column("source_gaps_json", _JSON, nullable=False),
        sa.Column("sources_json", _JSON, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["university_id"], ["universities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["ingest_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["manifest_hash"], ["source_snapshots.content_sha256"]),
        sa.PrimaryKeyConstraint("university_id", "admission_year", "source_run_id"),
        sa.CheckConstraint(
            "admission_year >= 2000 AND admission_year <= 2100",
            name="ck_benefit_coverage_year",
        ),
        sa.CheckConstraint(
            "status IN ('complete', 'partial', 'review_required', 'unavailable')",
            name="ck_benefit_coverage_status",
        ),
        sa.CheckConstraint(
            "documents_discovered >= 0 AND documents_selected >= 0 AND documents_captured >= 0 AND documents_parsed >= 0",
            name="ck_benefit_coverage_documents_nonnegative",
        ),
        sa.CheckConstraint(
            "documents_selected <= documents_discovered AND documents_captured <= documents_selected AND documents_parsed <= documents_captured",
            name="ck_benefit_coverage_document_order",
        ),
        sa.CheckConstraint(
            "required_documents_expected >= 0 AND required_documents_discovered >= 0 AND required_documents_captured >= 0",
            name="ck_benefit_coverage_required_nonnegative",
        ),
        sa.CheckConstraint(
            "required_documents_captured <= required_documents_discovered AND required_documents_discovered <= required_documents_expected",
            name="ck_benefit_coverage_required_order",
        ),
        sa.CheckConstraint(
            "records_normalized >= 0 AND targets_resolved >= 0 AND unresolved_targets >= 0 AND conflicts >= 0 AND review_required_rows >= 0",
            name="ck_benefit_coverage_counts_nonnegative",
        ),
    )
    op.create_index(
        "ix_benefit_coverage_university_year_recorded",
        "admission_benefit_ingestion_coverage",
        ["university_id", "admission_year", "recorded_at"],
    )
    op.create_index(
        "ix_benefit_coverage_run",
        "admission_benefit_ingestion_coverage",
        ["source_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_benefit_coverage_run", table_name="admission_benefit_ingestion_coverage"
    )
    op.drop_index(
        "ix_benefit_coverage_university_year_recorded",
        table_name="admission_benefit_ingestion_coverage",
    )
    op.drop_table("admission_benefit_ingestion_coverage")
