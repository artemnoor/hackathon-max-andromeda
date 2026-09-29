"""Add immutable audit attribution for operator-submitted knowledge candidates."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0050_knowledge_manual_submissions"
down_revision = "0049_knowledge_review_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_manual_submissions",
        sa.Column("submission_id", sa.String(length=96), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "actor_account_id",
            sa.String(length=64),
            sa.ForeignKey("accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "university_id",
            sa.String(length=128),
            sa.ForeignKey("universities.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("target_id", sa.String(length=140), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("target_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "source_observation_id",
            sa.String(length=64),
            sa.ForeignKey(
                "knowledge_source_observations.source_observation_id", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "submission_id LIKE 'knowledge-manual-submission:%'",
            name="ck_knowledge_manual_submission_id_prefix",
        ),
        sa.CheckConstraint(
            "kind IN ('source_snapshot', 'claim_candidate')",
            name="ck_knowledge_manual_submission_kind",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) = 64", name="ck_knowledge_manual_idempotency_hash"
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64 AND length(target_hash) = 64",
            name="ck_knowledge_manual_content_hashes",
        ),
        sa.CheckConstraint("target_revision >= 1", name="ck_knowledge_manual_target_revision"),
        sa.CheckConstraint("length(reason) > 0", name="ck_knowledge_manual_reason"),
        sa.CheckConstraint(
            "(kind = 'source_snapshot' AND target_id LIKE 'source-observation:%') OR "
            "(kind = 'claim_candidate' AND target_id LIKE 'claim:%' AND university_id IS NOT NULL)",
            name="ck_knowledge_manual_target_kind",
        ),
        sa.PrimaryKeyConstraint("submission_id", name="pk_knowledge_manual_submissions"),
        sa.UniqueConstraint(
            "actor_account_id",
            "idempotency_key",
            name="uq_knowledge_manual_actor_idempotency",
        ),
    )
    op.create_index(
        "ix_knowledge_manual_target_history",
        "knowledge_manual_submissions",
        ["target_id", "target_revision", "recorded_at"],
    )
    op.create_index(
        "ix_knowledge_manual_university_time",
        "knowledge_manual_submissions",
        ["university_id", "recorded_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text("SELECT COUNT(*) FROM knowledge_manual_submissions")
    ).scalar_one()
    if count:
        raise RuntimeError("Cannot drop knowledge manual submission audit history")
    op.drop_index(
        "ix_knowledge_manual_university_time", table_name="knowledge_manual_submissions"
    )
    op.drop_index(
        "ix_knowledge_manual_target_history", table_name="knowledge_manual_submissions"
    )
    op.drop_table("knowledge_manual_submissions")
