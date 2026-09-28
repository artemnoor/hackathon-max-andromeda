"""Index source claims for bounded, typed assistant lookup."""

from __future__ import annotations

from alembic import op

revision = "0054_claim_predicate_lookup_index"
down_revision = "0053_admission_offering_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_knowledge_claims_predicate_subject_time",
        "knowledge_claims",
        ["proposition_predicate", "proposition_subject_id", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_claims_predicate_subject_time",
        table_name="knowledge_claims",
    )
