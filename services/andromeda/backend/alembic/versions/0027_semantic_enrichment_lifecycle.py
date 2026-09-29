"""Add an independent semantic enrichment lifecycle and audit evidence."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0027_sem_enrich"
down_revision = "0026_semantic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("discipline_semantic_features", recreate="auto") as batch:
        batch.add_column(sa.Column("evidence_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))
    with op.batch_alter_table("curriculum_item_semantic_features", recreate="auto") as batch:
        batch.add_column(sa.Column("evidence_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(
            sa.Column("overrides_discipline_default", sa.Boolean(), nullable=False, server_default=sa.text("true"))
        )

    op.create_table(
        "semantic_enrichment_runs",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("ingest_run_id", sa.String(length=64), sa.ForeignKey("ingest_runs.id"), nullable=False),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("semantic_version", sa.String(length=64), nullable=False),
        sa.Column("classifier_version", sa.String(length=64), nullable=False),
        sa.Column("affected_item_ids_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("affected_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("classified_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_of_run_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_semantic_enrichment_run_status"),
        sa.CheckConstraint("affected_item_count >= 0", name="ck_semantic_enrichment_run_affected_count"),
        sa.CheckConstraint("classified_item_count >= 0", name="ck_semantic_enrichment_run_classified_count"),
        sa.CheckConstraint("unchanged_item_count >= 0", name="ck_semantic_enrichment_run_unchanged_count"),
        sa.CheckConstraint("failed_item_count >= 0", name="ck_semantic_enrichment_run_failed_count"),
    )
    op.create_index("ix_semantic_enrichment_runs_ingest_run", "semantic_enrichment_runs", ["ingest_run_id"])
    op.create_index(
        "ix_semantic_enrichment_runs_status_started",
        "semantic_enrichment_runs",
        ["status", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_semantic_enrichment_runs_status_started", table_name="semantic_enrichment_runs")
    op.drop_index("ix_semantic_enrichment_runs_ingest_run", table_name="semantic_enrichment_runs")
    op.drop_table("semantic_enrichment_runs")
    with op.batch_alter_table("curriculum_item_semantic_features", recreate="auto") as batch:
        batch.drop_column("overrides_discipline_default")
        batch.drop_column("evidence_json")
    with op.batch_alter_table("discipline_semantic_features", recreate="auto") as batch:
        batch.drop_column("evidence_json")
