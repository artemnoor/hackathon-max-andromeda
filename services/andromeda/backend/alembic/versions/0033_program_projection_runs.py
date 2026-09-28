"""Persist independent projection rebuild runs and last-good status."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0033_projection_runs"
down_revision = "0032_semantic_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program_projection_runs",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("ingest_run_id", sa.String(length=64), sa.ForeignKey("ingest_runs.id"), nullable=True),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.Column("projection_version", sa.String(length=64), nullable=False),
        sa.Column("semantic_version", sa.String(length=64), nullable=True),
        sa.Column("classifier_version", sa.String(length=64), nullable=True),
        sa.Column("input_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("affected_program_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refreshed_program_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("university_id", "projection_version", "input_hash", name="uq_projection_run_target"),
        sa.CheckConstraint("status IN ('running', 'completed', 'partial', 'failed')", name="ck_projection_run_status"),
        sa.CheckConstraint("affected_program_count >= 0", name="ck_projection_run_affected_count"),
        sa.CheckConstraint("refreshed_program_count >= 0", name="ck_projection_run_refreshed_count"),
    )
    op.create_index("ix_projection_runs_status_started", "program_projection_runs", ["status", "started_at"])
    op.create_index("ix_projection_runs_ingest", "program_projection_runs", ["ingest_run_id"])

    if op.get_bind().dialect.name == "sqlite":
        # SQLite needs a table rebuild to add a foreign key constraint. Keep
        # the existing SQLite path for tests and local development.
        with op.batch_alter_table("program_projections", recreate="always") as batch:
            batch.add_column(sa.Column("projection_run_id", sa.String(length=128), nullable=True))
            batch.add_column(sa.Column("input_hash", sa.String(length=128), nullable=True))
            batch.add_column(
                sa.Column(
                    "materialization_status",
                    sa.String(length=16),
                    nullable=False,
                    server_default="active",
                )
            )
            batch.create_foreign_key(
                "fk_program_projections_projection_run",
                "program_projection_runs",
                ["projection_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_check_constraint(
                "ck_program_projection_materialization_status",
                "materialization_status IN ('active', 'stale', 'failed')",
            )
    else:
        # PostgreSQL cannot drop/recreate the referenced projection PK while
        # the metrics and evidence tables still hold foreign keys to it.
        op.add_column(
            "program_projections",
            sa.Column("projection_run_id", sa.String(length=128), nullable=True),
        )
        op.add_column("program_projections", sa.Column("input_hash", sa.String(length=128), nullable=True))
        op.add_column(
            "program_projections",
            sa.Column(
                "materialization_status",
                sa.String(length=16),
                nullable=False,
                server_default="active",
            ),
        )
        op.create_foreign_key(
            "fk_program_projections_projection_run",
            "program_projections",
            "program_projection_runs",
            ["projection_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_check_constraint(
            "ck_program_projection_materialization_status",
            "program_projections",
            "materialization_status IN ('active', 'stale', 'failed')",
        )
    op.create_index("ix_program_projections_materialization", "program_projections", ["materialization_status", "schema_version"])


def downgrade() -> None:
    op.drop_index("ix_program_projections_materialization", table_name="program_projections")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("program_projections", recreate="always") as batch:
            batch.drop_constraint("ck_program_projection_materialization_status", type_="check")
            batch.drop_constraint("fk_program_projections_projection_run", type_="foreignkey")
            batch.drop_column("materialization_status")
            batch.drop_column("input_hash")
            batch.drop_column("projection_run_id")
    else:
        op.drop_constraint(
            "ck_program_projection_materialization_status",
            "program_projections",
            type_="check",
        )
        op.drop_constraint(
            "fk_program_projections_projection_run",
            "program_projections",
            type_="foreignkey",
        )
        op.drop_column("program_projections", "materialization_status")
        op.drop_column("program_projections", "input_hash")
        op.drop_column("program_projections", "projection_run_id")
    op.drop_index("ix_projection_runs_ingest", table_name="program_projection_runs")
    op.drop_index("ix_projection_runs_status_started", table_name="program_projection_runs")
    op.drop_table("program_projection_runs")
