"""Persist university-scoped administration memberships."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0023_uni_admin"
down_revision = "0022_ingestion_concurrency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "university_admin_memberships",
        sa.Column("membership_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by_account_id", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"]),
        sa.ForeignKeyConstraint(["granted_by_account_id"], ["accounts.account_id"]),
        sa.PrimaryKeyConstraint("membership_id"),
        sa.UniqueConstraint("account_id", "university_id", name="uq_university_admin_membership_scope"),
        sa.CheckConstraint("membership_id LIKE 'membership:%'", name="ck_university_admin_membership_id"),
        sa.CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name="ck_university_admin_membership_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_university_admin_membership_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_university_admin_membership_revision"),
        sa.CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_university_admin_membership_revocation",
        ),
    )
    op.create_index(
        "ix_university_admin_memberships_university_status",
        "university_admin_memberships",
        ["university_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_university_admin_memberships_university_status",
        table_name="university_admin_memberships",
    )
    op.drop_table("university_admin_memberships")
