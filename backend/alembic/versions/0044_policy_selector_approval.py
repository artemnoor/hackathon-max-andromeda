"""Persist bounded policy selectors and the exact-revision approval ledger."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0044_policy_selector_approval"
down_revision = "0043_knowledge_exact_claim_clusters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    selector_json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "policy_rule_revisions",
        sa.Column("rule_id", sa.String(length=140), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("selector_json", selector_json, nullable=False),
        sa.Column("scope_level", sa.String(length=40), nullable=False),
        sa.Column("scope_id", sa.String(length=320), nullable=True),
        sa.Column("owner_module", sa.String(length=40), nullable=False),
        sa.Column("owner_rule_id", sa.String(length=320), nullable=False),
        sa.Column("owner_revision", sa.Integer(), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("valid_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rule_id LIKE 'policy-rule:%'", name="ck_policy_rule_id_prefix"),
        sa.CheckConstraint("revision >= 1", name="ck_policy_rule_revision_positive"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_policy_rule_content_hash_length"),
        sa.CheckConstraint("schema_version = 'policy-rule.v1'", name="ck_policy_rule_schema_version"),
        sa.CheckConstraint(
            "scope_level IN ('federal', 'ministry', 'university', 'campus', 'faculty', 'department', "
            "'education_level', 'direction', 'program', 'admission_route', 'competition_type', "
            "'applicant_category', 'olympiad', 'olympiad_profile', 'subject')",
            name="ck_policy_rule_scope_level",
        ),
        sa.CheckConstraint(
            "(scope_level = 'federal' AND scope_id IS NULL) OR "
            "(scope_level != 'federal' AND scope_id IS NOT NULL AND length(scope_id) > 0)",
            name="ck_policy_rule_scope_reference",
        ),
        sa.CheckConstraint(
            "owner_module IN ('admission_benefits', 'admissions', 'admission_fit')",
            name="ck_policy_rule_owner_module",
        ),
        sa.CheckConstraint("owner_revision >= 1", name="ck_policy_rule_owner_revision"),
        sa.CheckConstraint(
            "lifecycle IN ('rumor', 'hypothesis', 'announced', 'proposal', 'draft', 'under_review', "
            "'adopted', 'published', 'future_effective', 'effective', 'superseded', 'repealed', "
            "'withdrawn', 'rejected', 'unknown')",
            name="ck_policy_rule_lifecycle",
        ),
        sa.CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR "
            "valid_start IS NOT NULL AND (valid_end IS NULL OR valid_start < valid_end)",
            name="ck_policy_rule_valid_period",
        ),
        sa.CheckConstraint(
            "effective_start IS NULL AND effective_end IS NULL OR "
            "effective_start IS NOT NULL AND (effective_end IS NULL OR effective_start < effective_end)",
            name="ck_policy_rule_effective_period",
        ),
        sa.CheckConstraint("recorded_at >= captured_at", name="ck_policy_rule_recorded_after_capture"),
        sa.PrimaryKeyConstraint("rule_id", "revision"),
        sa.UniqueConstraint("rule_id", "content_hash", name="uq_policy_rule_content_hash"),
    )
    op.create_index(
        "ix_policy_rule_scope_lifecycle",
        "policy_rule_revisions",
        ["scope_level", "scope_id", "lifecycle"],
    )
    op.create_index("ix_policy_rule_recorded_at", "policy_rule_revisions", ["rule_id", "recorded_at"])
    op.create_index(
        "ix_policy_rule_effective_period",
        "policy_rule_revisions",
        ["effective_start", "effective_end"],
    )
    op.create_table(
        "policy_rule_revision_claims",
        sa.Column("rule_id", sa.String(length=140), nullable=False),
        sa.Column("rule_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.String(length=70), nullable=False),
        sa.Column("claim_revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_policy_rule_claim_ordinal"),
        sa.ForeignKeyConstraint(
            ["rule_id", "rule_revision"],
            ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision"],
            name="fk_policy_rule_claim_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            name="fk_policy_rule_source_claim",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rule_id", "rule_revision", "ordinal"),
        sa.UniqueConstraint(
            "rule_id", "rule_revision", "claim_id", "claim_revision",
            name="uq_policy_rule_claim_ref",
        ),
    )
    op.create_index(
        "ix_policy_rule_claim_claim",
        "policy_rule_revision_claims",
        ["claim_id", "claim_revision"],
    )
    op.create_table(
        "policy_rule_revision_evidence",
        sa.Column("rule_id", sa.String(length=140), nullable=False),
        sa.Column("rule_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_observation_id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("locator_page", sa.Integer(), nullable=True),
        sa.Column("locator_table", sa.String(length=256), nullable=True),
        sa.Column("locator_row", sa.Integer(), nullable=True),
        sa.Column("locator_section", sa.String(length=512), nullable=True),
        sa.Column("locator_field", sa.String(length=128), nullable=True),
        sa.Column("locator_record_key", sa.String(length=256), nullable=True),
        sa.Column("inferred", sa.Boolean(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_policy_rule_evidence_ordinal"),
        sa.CheckConstraint("length(source_url) > 0", name="ck_policy_rule_evidence_url"),
        sa.CheckConstraint("locator_page IS NULL OR locator_page >= 1", name="ck_policy_rule_evidence_page"),
        sa.CheckConstraint("locator_row IS NULL OR locator_row >= 1", name="ck_policy_rule_evidence_row"),
        sa.ForeignKeyConstraint(
            ["rule_id", "rule_revision"],
            ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision"],
            name="fk_policy_rule_evidence_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["knowledge_source_observations.source_observation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("rule_id", "rule_revision", "ordinal"),
    )
    op.create_index(
        "ix_policy_rule_evidence_observation",
        "policy_rule_revision_evidence",
        ["source_observation_id"],
    )
    op.create_table(
        "policy_approval_events",
        sa.Column("event_id", sa.String(length=88), nullable=False),
        sa.Column("rule_id", sa.String(length=140), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("actor_account_id", sa.String(length=128), nullable=False),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_id LIKE 'policy-approval-event:%'", name="ck_policy_approval_event_id_prefix"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_policy_approval_sequence"),
        sa.CheckConstraint("length(revision_hash) = 64", name="ck_policy_approval_revision_hash"),
        sa.CheckConstraint(
            "kind IN ('pending_submitted', 'approved', 'rejected', 'withdrawn')",
            name="ck_policy_approval_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'pending_submitted' AND capability = 'policy.submit_revision') OR "
            "(kind != 'pending_submitted' AND capability = 'policy.approve_revision')",
            name="ck_policy_approval_capability_kind",
        ),
        sa.CheckConstraint("length(reason) > 0", name="ck_policy_approval_reason"),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.account_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["rule_id", "revision"],
            ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision"],
            name="fk_policy_approval_rule_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("rule_id", "revision", "sequence", name="uq_policy_approval_sequence"),
    )
    op.create_index(
        "ix_policy_approval_history",
        "policy_approval_events",
        ["rule_id", "revision", "sequence"],
    )
    op.create_index(
        "ix_policy_approval_actor_time",
        "policy_approval_events",
        ["actor_account_id", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_policy_approval_actor_time", table_name="policy_approval_events")
    op.drop_index("ix_policy_approval_history", table_name="policy_approval_events")
    op.drop_table("policy_approval_events")
    op.drop_index("ix_policy_rule_evidence_observation", table_name="policy_rule_revision_evidence")
    op.drop_table("policy_rule_revision_evidence")
    op.drop_index("ix_policy_rule_claim_claim", table_name="policy_rule_revision_claims")
    op.drop_table("policy_rule_revision_claims")
    op.drop_index("ix_policy_rule_effective_period", table_name="policy_rule_revisions")
    op.drop_index("ix_policy_rule_recorded_at", table_name="policy_rule_revisions")
    op.drop_index("ix_policy_rule_scope_lifecycle", table_name="policy_rule_revisions")
    op.drop_table("policy_rule_revisions")
