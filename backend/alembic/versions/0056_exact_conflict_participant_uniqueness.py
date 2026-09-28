"""Enforce exact participant uniqueness without nullable discriminator columns."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0056_exact_conflict_participant_uniqueness"
down_revision = "0055_knowledge_schema_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "uq_knowledge_conflict_participant_exact_ref",
        table_name="knowledge_conflict_participants",
    )
    op.create_index(
        "uq_knowledge_conflict_participant_claim_ref",
        "knowledge_conflict_participants",
        ["conflict_id", "group_revision", "claim_id", "claim_revision", "claim_hash"],
        unique=True,
        sqlite_where=sa.text("participant_kind = 'claim_revision'"),
        postgresql_where=sa.text("participant_kind = 'claim_revision'"),
    )
    op.create_index(
        "uq_knowledge_conflict_participant_change_event_ref",
        "knowledge_conflict_participants",
        ["conflict_id", "group_revision", "change_event_id", "change_event_revision"],
        unique=True,
        sqlite_where=sa.text("participant_kind = 'change_event_revision'"),
        postgresql_where=sa.text("participant_kind = 'change_event_revision'"),
    )
    op.create_index(
        "uq_knowledge_conflict_participant_policy_ref",
        "knowledge_conflict_participants",
        ["conflict_id", "group_revision", "policy_rule_id", "policy_revision", "policy_hash"],
        unique=True,
        sqlite_where=sa.text("participant_kind = 'policy_rule_revision'"),
        postgresql_where=sa.text("participant_kind = 'policy_rule_revision'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_knowledge_conflict_participant_policy_ref",
        table_name="knowledge_conflict_participants",
    )
    op.drop_index(
        "uq_knowledge_conflict_participant_change_event_ref",
        table_name="knowledge_conflict_participants",
    )
    op.drop_index(
        "uq_knowledge_conflict_participant_claim_ref",
        table_name="knowledge_conflict_participants",
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
