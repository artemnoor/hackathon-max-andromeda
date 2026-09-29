"""Add targeted policy projection refresh state and immutable attempts."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0048_policy_projection_refresh"
down_revision = "0047_typed_knowledge_relations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_projection_refresh_state",
        sa.Column("refresh_key", sa.String(length=80), nullable=False),
        sa.Column("target_kind", sa.String(length=24), nullable=False),
        sa.Column("target_object_id", sa.String(length=320), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=True),
        sa.Column("target_content_hash", sa.String(length=64), nullable=True),
        sa.Column("target_owner_module", sa.String(length=64), nullable=True),
        sa.Column("projection_kind", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("completed_generation", sa.Integer(), nullable=False),
        sa.Column(
            "invalidated_by_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("invalidation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("projection_version", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint("refresh_key LIKE 'policy-refresh:%'", name="ck_policy_refresh_key_prefix"),
        sa.CheckConstraint(
            "target_kind IN ('policy_rule', 'domain_rule', 'scope')",
            name="ck_policy_refresh_target_kind",
        ),
        sa.CheckConstraint(
            "(target_kind = 'policy_rule' AND target_revision IS NOT NULL AND "
            "target_content_hash IS NOT NULL AND target_owner_module IS NULL) OR "
            "(target_kind = 'domain_rule' AND target_revision IS NOT NULL AND "
            "target_content_hash IS NULL AND target_owner_module IS NOT NULL) OR "
            "(target_kind = 'scope' AND target_revision IS NULL AND "
            "target_content_hash IS NULL AND target_owner_module IS NULL)",
            name="ck_policy_refresh_target_shape",
        ),
        sa.CheckConstraint(
            "projection_kind IN ('effective_policy', 'domain_impact', 'dependency_closure')",
            name="ck_policy_refresh_projection_kind",
        ),
        sa.CheckConstraint("generation >= 1", name="ck_policy_refresh_generation"),
        sa.CheckConstraint(
            "completed_generation >= 0 AND completed_generation <= generation",
            name="ck_policy_refresh_completed_generation",
        ),
        sa.CheckConstraint("length(invalidation_fingerprint) = 64", name="ck_policy_refresh_fingerprint"),
        sa.CheckConstraint("state IN ('dirty', 'ready', 'failed')", name="ck_policy_refresh_state"),
        sa.CheckConstraint(
            "(state = 'ready' AND completed_generation = generation AND "
            "projection_version IS NOT NULL AND last_success_at IS NOT NULL AND failure_code IS NULL) OR "
            "(state = 'dirty' AND completed_generation < generation AND failure_code IS NULL) OR "
            "(state = 'failed' AND completed_generation < generation AND failure_code IS NOT NULL)",
            name="ck_policy_refresh_state_generation",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_policy_refresh_attempt_count"),
        sa.PrimaryKeyConstraint("refresh_key", name="pk_policy_projection_refresh_state"),
    )
    op.create_index(
        "ix_policy_projection_refresh_pending",
        "policy_projection_refresh_state",
        ["state", "last_updated_at"],
    )
    op.create_index(
        "ix_policy_projection_refresh_target",
        "policy_projection_refresh_state",
        ["target_kind", "target_object_id"],
    )
    op.create_table(
        "policy_projection_refresh_attempts",
        sa.Column("attempt_id", sa.String(length=96), nullable=False),
        sa.Column("refresh_key", sa.String(length=80), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("projection_version", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempt_id LIKE 'policy-refresh-attempt:%'", name="ck_policy_refresh_attempt_id_prefix"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_policy_refresh_attempt_sequence"),
        sa.CheckConstraint("generation >= 1", name="ck_policy_refresh_attempt_generation"),
        sa.CheckConstraint(
            "(outcome = 'completed' AND projection_version IS NOT NULL AND failure_code IS NULL) OR "
            "(outcome = 'failed' AND projection_version IS NULL AND failure_code IS NOT NULL) OR "
            "(outcome = 'stale_result_rejected' AND projection_version IS NOT NULL AND failure_code IS NOT NULL)",
            name="ck_policy_refresh_attempt_result",
        ),
        sa.ForeignKeyConstraint(
            ["refresh_key"],
            ["policy_projection_refresh_state.refresh_key"],
            ondelete="RESTRICT",
            name="fk_policy_refresh_attempt_state",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name="pk_policy_projection_refresh_attempts"),
        sa.UniqueConstraint("refresh_key", "sequence", name="uq_policy_refresh_attempt_sequence"),
    )
    op.create_index(
        "ix_policy_refresh_attempt_history",
        "policy_projection_refresh_attempts",
        ["refresh_key", "sequence"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    attempts = bind.execute(
        sa.text("SELECT COUNT(*) FROM policy_projection_refresh_attempts")
    ).scalar_one()
    state_rows = bind.execute(
        sa.text("SELECT COUNT(*) FROM policy_projection_refresh_state")
    ).scalar_one()
    if attempts or state_rows:
        raise RuntimeError("Refusing to downgrade policy refresh history containing data")
    op.drop_index("ix_policy_refresh_attempt_history", table_name="policy_projection_refresh_attempts")
    op.drop_table("policy_projection_refresh_attempts")
    op.drop_index("ix_policy_projection_refresh_target", table_name="policy_projection_refresh_state")
    op.drop_index("ix_policy_projection_refresh_pending", table_name="policy_projection_refresh_state")
    op.drop_table("policy_projection_refresh_state")
