"""Bind human policy decisions to the exact reviewer preview."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0052_policy_approval_preview_fingerprint"
down_revision = "0051_policy_domain_owner_revision_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("policy_approval_events", recreate="auto") as batch:
        batch.add_column(
            sa.Column("preview_fingerprint", sa.String(length=64), nullable=True)
        )
        batch.create_check_constraint(
            "ck_policy_approval_preview_fingerprint",
            "preview_fingerprint IS NULL OR length(preview_fingerprint) = 64",
        )


def downgrade() -> None:
    bind = op.get_bind()
    linked_approvals = bind.execute(
        sa.text(
            "SELECT count(*) FROM policy_approval_events "
            "WHERE preview_fingerprint IS NOT NULL"
        )
    ).scalar_one()
    if linked_approvals:
        raise RuntimeError("Cannot downgrade policy decisions linked to review previews")
    with op.batch_alter_table("policy_approval_events", recreate="auto") as batch:
        batch.drop_constraint(
            "ck_policy_approval_preview_fingerprint", type_="check"
        )
        batch.drop_column("preview_fingerprint")
