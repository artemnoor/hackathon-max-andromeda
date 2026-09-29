"""Keep immutable, exact source-backed admissions owner revisions."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0053_admission_offering_revisions"
down_revision = "0052_policy_approval_preview_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admission_offering_revisions",
        sa.Column("domain_rule_id", sa.String(length=96), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("offering_id", sa.String(length=320), nullable=False),
        sa.Column("program_id", sa.String(length=128), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.CheckConstraint("revision >= 1", name="ck_admission_offering_revision_positive"),
        sa.CheckConstraint(
            "admission_year >= 2000 AND admission_year <= 2100",
            name="ck_admission_offering_revision_year",
        ),
        sa.CheckConstraint(
            "length(domain_rule_id) = 83",
            name="ck_admission_offering_revision_domain_id",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_admission_offering_revision_sha256",
        ),
        sa.PrimaryKeyConstraint("domain_rule_id", "revision"),
    )
    op.create_index(
        "ix_admission_offering_revisions_program_year",
        "admission_offering_revisions",
        ["program_id", "admission_year", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT count(*) FROM admission_offering_revisions")
    ).scalar_one()
    if rows:
        raise RuntimeError("Cannot downgrade persisted admission owner revisions")
    op.drop_index(
        "ix_admission_offering_revisions_program_year",
        table_name="admission_offering_revisions",
    )
    op.drop_table("admission_offering_revisions")
