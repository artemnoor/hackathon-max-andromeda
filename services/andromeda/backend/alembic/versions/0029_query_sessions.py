"""Persist owner-bound generic conversation sessions."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0029_query"
down_revision = "0028_prog_proj"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "query_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("owner_key", sa.String(length=320), nullable=False),
        sa.Column("session_key_hash", sa.String(length=64), nullable=True),
        sa.Column("account_id", sa.String(length=128), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("session_id"),
        sa.CheckConstraint("length(session_id) > 0", name="ck_query_session_id_non_empty"),
        sa.CheckConstraint("length(owner_key) > 0", name="ck_query_session_owner_non_empty"),
        sa.CheckConstraint("revision >= 1", name="ck_query_session_revision_positive"),
        sa.CheckConstraint("expires_at > updated_at", name="ck_query_session_expiry_after_update"),
        sa.CheckConstraint(
            "(account_id IS NOT NULL AND session_key_hash IS NULL) OR (account_id IS NULL AND session_key_hash IS NOT NULL)",
            name="ck_query_session_owner_identity",
        ),
    )
    op.create_index("ix_query_sessions_owner_updated", "query_sessions", ["owner_key", "updated_at"])
    op.create_index("ix_query_sessions_expiry", "query_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_query_sessions_expiry", table_name="query_sessions")
    op.drop_index("ix_query_sessions_owner_updated", table_name="query_sessions")
    op.drop_table("query_sessions")
