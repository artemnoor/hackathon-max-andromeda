"""Align knowledge foreign key widths and participant uniqueness with models."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0055_knowledge_schema_alignment"
down_revision = "0054_claim_predicate_lookup_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_conflict_events") as batch_op:
        batch_op.alter_column(
            "actor_account_id",
            existing_type=sa.String(length=64),
            type_=sa.String(length=128),
            existing_nullable=True,
        )

    with op.batch_alter_table("knowledge_review_actions") as batch_op:
        batch_op.alter_column(
            "actor_account_id",
            existing_type=sa.String(length=64),
            type_=sa.String(length=128),
            existing_nullable=False,
        )

    with op.batch_alter_table("knowledge_manual_submissions") as batch_op:
        batch_op.alter_column(
            "actor_account_id",
            existing_type=sa.String(length=64),
            type_=sa.String(length=128),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "university_id",
            existing_type=sa.String(length=128),
            type_=sa.String(length=64),
            existing_nullable=True,
        )

    op.create_index(
        "uq_knowledge_conflict_participant_exact_ref",
        "knowledge_conflict_participants",
        [
            "conflict_id",
            "group_revision",
            "participant_kind",
            "claim_id",
            "claim_revision",
            "change_event_id",
            "change_event_revision",
            "policy_rule_id",
            "policy_revision",
            "policy_hash",
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_knowledge_conflict_participant_exact_ref",
        table_name="knowledge_conflict_participants",
    )

    with op.batch_alter_table("knowledge_manual_submissions") as batch_op:
        batch_op.alter_column(
            "university_id",
            existing_type=sa.String(length=64),
            type_=sa.String(length=128),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "actor_account_id",
            existing_type=sa.String(length=128),
            type_=sa.String(length=64),
            existing_nullable=False,
        )

    with op.batch_alter_table("knowledge_review_actions") as batch_op:
        batch_op.alter_column(
            "actor_account_id",
            existing_type=sa.String(length=128),
            type_=sa.String(length=64),
            existing_nullable=False,
        )

    with op.batch_alter_table("knowledge_conflict_events") as batch_op:
        batch_op.alter_column(
            "actor_account_id",
            existing_type=sa.String(length=128),
            type_=sa.String(length=64),
            existing_nullable=True,
        )
