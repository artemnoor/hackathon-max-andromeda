"""Add review and definition metadata to inferred semantic values."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0032_semantic_review"
down_revision = "0031_sem_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "semantic_features",
        sa.Column("definition_version", sa.String(length=64), nullable=False, server_default="semantic-taxonomy.v1"),
    )
    op.add_column("semantic_features", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("semantic_features", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_semantic_features_definition_active",
        "semantic_features",
        ["definition_version", "active", "code"],
    )
    for table, prefix in (
        ("discipline_semantic_features", "discipline"),
        ("curriculum_item_semantic_features", "curriculum_item"),
    ):
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.add_column(sa.Column("review_status", sa.String(length=16), nullable=False, server_default="unreviewed"))
            batch.create_check_constraint(
                f"ck_{prefix}_semantic_review_status",
                "review_status IN ('unreviewed', 'reviewed', 'rejected', 'needs_review')",
            )


def downgrade() -> None:
    for table, prefix in (
        ("curriculum_item_semantic_features", "curriculum_item"),
        ("discipline_semantic_features", "discipline"),
    ):
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(f"ck_{prefix}_semantic_review_status", type_="check")
            batch.drop_column("review_status")
    op.drop_index("ix_semantic_features_definition_active", table_name="semantic_features")
    op.drop_column("semantic_features", "retired_at")
    op.drop_column("semantic_features", "active")
    op.drop_column("semantic_features", "definition_version")
