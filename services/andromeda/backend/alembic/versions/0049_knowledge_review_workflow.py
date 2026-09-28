"""Add auditable review transitions for claims and change-event candidates."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0049_knowledge_review_workflow"
down_revision = "0048_policy_projection_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_claims") as batch:
        batch.drop_constraint("ck_knowledge_claim_review_state", type_="check")
        batch.drop_constraint("ck_knowledge_claim_jev_needs_review", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_claim_review_state",
            "review_state IN ('unreviewed', 'needs_review', 'accepted_as_source_assertion', "
            "'rejected', 'unresolved', 'duplicate')",
        )
        batch.create_check_constraint(
            "ck_knowledge_claim_jev_confidence",
            "extraction_method != 'jev_suggestion' OR extraction_confidence IS NOT NULL",
        )

    with op.batch_alter_table("knowledge_change_events") as batch:
        batch.drop_constraint("ck_knowledge_change_event_review_state", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_change_event_review_state",
            "review_state IN ('needs_review', 'accepted_as_source_event', 'rejected', "
            "'unresolved', 'duplicate')",
        )

    op.create_table(
        "knowledge_review_actions",
        sa.Column("event_id", sa.String(length=96), nullable=False),
        sa.Column("idempotency_key", sa.String(length=84), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("target_kind", sa.String(length=24), nullable=False),
        sa.Column("target_id", sa.String(length=140), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("target_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("result_id", sa.String(length=140), nullable=False),
        sa.Column("result_revision", sa.Integer(), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("related_kind", sa.String(length=24), nullable=True),
        sa.Column("related_id", sa.String(length=140), nullable=True),
        sa.Column("related_revision", sa.Integer(), nullable=True),
        sa.Column("related_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "actor_account_id",
            sa.String(length=64),
            sa.ForeignKey("accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_id LIKE 'knowledge-review-action:%'",
            name="ck_knowledge_review_action_id_prefix",
        ),
        sa.CheckConstraint(
            "idempotency_key LIKE 'review-idempotency:%'",
            name="ck_knowledge_review_idempotency_prefix",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64 AND length(target_hash) = 64 AND "
            "length(result_hash) = 64",
            name="ck_knowledge_review_hash_lengths",
        ),
        sa.CheckConstraint(
            "target_kind IN ('claim', 'change_event') AND "
            "((target_kind = 'claim' AND target_id LIKE 'claim:%') OR "
            "(target_kind = 'change_event' AND target_id LIKE 'change-event:%'))",
            name="ck_knowledge_review_target_kind",
        ),
        sa.CheckConstraint("target_revision >= 1", name="ck_knowledge_review_target_revision"),
        sa.CheckConstraint(
            "result_id = target_id AND result_revision = target_revision + 1",
            name="ck_knowledge_review_result_revision",
        ),
        sa.CheckConstraint(
            "action IN ('approve', 'reject', 'edit', 'merge', 'resolve_identity', "
            "'mark_unresolved', 'mark_duplicate')",
            name="ck_knowledge_review_action_kind",
        ),
        sa.CheckConstraint(
            "(action IN ('merge', 'mark_duplicate') AND related_kind = target_kind AND "
            "related_id IS NOT NULL AND related_revision IS NOT NULL AND "
            "related_hash IS NOT NULL) OR "
            "(action NOT IN ('merge', 'mark_duplicate') AND related_kind IS NULL AND "
            "related_id IS NULL AND related_revision IS NULL AND related_hash IS NULL)",
            name="ck_knowledge_review_related_target",
        ),
        sa.CheckConstraint(
            "(action = 'edit' AND capability = 'knowledge.edit_candidate') OR "
            "(action = 'resolve_identity' AND capability = 'knowledge.resolve_identity') OR "
            "(action NOT IN ('edit', 'resolve_identity') AND "
            "capability = 'knowledge.review_candidate')",
            name="ck_knowledge_review_capability",
        ),
        sa.CheckConstraint("length(reason) > 0", name="ck_knowledge_review_reason"),
        sa.PrimaryKeyConstraint("event_id", name="pk_knowledge_review_actions"),
        sa.UniqueConstraint(
            "actor_account_id",
            "idempotency_key",
            name="uq_knowledge_review_actor_idempotency",
        ),
    )
    op.create_index(
        "ix_knowledge_review_target_history",
        "knowledge_review_actions",
        ["target_kind", "target_id", "recorded_at"],
    )
    op.create_index(
        "ix_knowledge_review_actor_time",
        "knowledge_review_actions",
        ["actor_account_id", "recorded_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    action_count = bind.execute(sa.text("SELECT COUNT(*) FROM knowledge_review_actions")).scalar_one()
    duplicate_claims = bind.execute(
        sa.text("SELECT COUNT(*) FROM knowledge_claims WHERE review_state = 'duplicate'")
    ).scalar_one()
    duplicate_events = bind.execute(
        sa.text("SELECT COUNT(*) FROM knowledge_change_events WHERE review_state = 'duplicate'")
    ).scalar_one()
    reviewed_jev_claims = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM knowledge_claims WHERE extraction_method = 'jev_suggestion' "
            "AND review_state NOT IN ('unreviewed', 'needs_review')"
        )
    ).scalar_one()
    if action_count or duplicate_claims or duplicate_events or reviewed_jev_claims:
        raise RuntimeError("Refusing to downgrade persisted knowledge review decisions")

    op.drop_index("ix_knowledge_review_actor_time", table_name="knowledge_review_actions")
    op.drop_index("ix_knowledge_review_target_history", table_name="knowledge_review_actions")
    op.drop_table("knowledge_review_actions")
    with op.batch_alter_table("knowledge_change_events") as batch:
        batch.drop_constraint("ck_knowledge_change_event_review_state", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_change_event_review_state",
            "review_state IN ('needs_review', 'accepted_as_source_event', 'rejected', 'unresolved')",
        )
    with op.batch_alter_table("knowledge_claims") as batch:
        batch.drop_constraint("ck_knowledge_claim_review_state", type_="check")
        batch.drop_constraint("ck_knowledge_claim_jev_confidence", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_claim_review_state",
            "review_state IN ('unreviewed', 'needs_review', 'accepted_as_source_assertion', "
            "'rejected', 'unresolved')",
        )
        batch.create_check_constraint(
            "ck_knowledge_claim_jev_needs_review",
            "extraction_method != 'jev_suggestion' OR "
            "(extraction_confidence IS NOT NULL AND review_state IN ('unreviewed', 'needs_review'))",
        )
