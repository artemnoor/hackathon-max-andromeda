"""Track bounded policy-source discovery health and content changes."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0042_knowledge_source_poll_attempts"
down_revision = "0041_knowledge_claims_and_change_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_source_poll_attempts",
        sa.Column("attempt_id", sa.String(length=45), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("registry_revision", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("previous_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column("last_successful_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_observation_id", sa.String(length=64), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("extracted_candidate_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("attempt_id LIKE 'poll-attempt:%'", name="ck_knowledge_poll_attempt_id_prefix"),
        sa.CheckConstraint(
            "outcome IN ('new', 'changed', 'unchanged', 'unavailable', 'removed')",
            name="ck_knowledge_poll_outcome",
        ),
        sa.CheckConstraint("length(parser_version) > 0", name="ck_knowledge_poll_parser_version"),
        sa.CheckConstraint("retry_count BETWEEN 0 AND 10", name="ck_knowledge_poll_retry_count"),
        sa.CheckConstraint(
            "extracted_candidate_count BETWEEN 0 AND 500",
            name="ck_knowledge_poll_candidate_count",
        ),
        sa.CheckConstraint(
            "(previous_snapshot_sha256 IS NULL OR length(previous_snapshot_sha256) = 64) AND "
            "(snapshot_sha256 IS NULL OR length(snapshot_sha256) = 64) AND "
            "(last_successful_snapshot_sha256 IS NULL OR length(last_successful_snapshot_sha256) = 64)",
            name="ck_knowledge_poll_snapshot_hash_lengths",
        ),
        sa.CheckConstraint("completed_at >= started_at", name="ck_knowledge_poll_time_order"),
        sa.CheckConstraint(
            "next_retry_at IS NULL OR next_retry_at > completed_at",
            name="ck_knowledge_poll_retry_after_completion",
        ),
        sa.CheckConstraint(
            "(outcome IN ('new', 'changed', 'unchanged') AND source_observation_id IS NOT NULL "
            "AND snapshot_sha256 IS NOT NULL AND failure_code IS NULL AND next_retry_at IS NULL AND retry_count = 0) OR "
            "(outcome IN ('unavailable', 'removed') AND source_observation_id IS NULL "
            "AND snapshot_sha256 IS NULL AND failure_code IS NOT NULL AND next_retry_at IS NOT NULL "
            "AND extracted_candidate_count = 0)",
            name="ck_knowledge_poll_success_failure_shape",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "registry_revision"],
            ["knowledge_source_registry_revisions.source_id", "knowledge_source_registry_revisions.revision"],
            name="fk_knowledge_source_poll_attempt_registry_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["knowledge_source_observations.source_observation_id"],
            name="fk_knowledge_source_poll_attempt_observation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    op.create_index(
        "ix_knowledge_poll_attempt_source_time",
        "knowledge_source_poll_attempts",
        ["source_id", "completed_at"],
    )
    op.create_index(
        "ix_knowledge_poll_attempt_next_retry",
        "knowledge_source_poll_attempts",
        ["next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_poll_attempt_next_retry", table_name="knowledge_source_poll_attempts")
    op.drop_index("ix_knowledge_poll_attempt_source_time", table_name="knowledge_source_poll_attempts")
    op.drop_table("knowledge_source_poll_attempts")
