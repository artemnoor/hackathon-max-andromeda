"""Add exact typed claim relations and extend policy dependency edges."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0047_typed_knowledge_relations"
down_revision = "0046_knowledge_conflict_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("policy_rule_relations") as batch:
        batch.drop_constraint("ck_policy_rule_relation_kind", type_="check")
        batch.create_check_constraint(
            "ck_policy_rule_relation_kind",
            "relation_kind IN ('exception_to', 'authorized_exception_to', 'overrides', "
            "'supersedes', 'amends', 'requires')",
        )

    op.create_table(
        "knowledge_claim_relations",
        sa.Column("relation_id", sa.String(length=96), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("relation_kind", sa.String(length=24), nullable=False),
        sa.Column("source_claim_id", sa.String(length=70), nullable=False),
        sa.Column("source_claim_revision", sa.Integer(), nullable=False),
        sa.Column("target_claim_id", sa.String(length=70), nullable=False),
        sa.Column("target_claim_revision", sa.Integer(), nullable=False),
        sa.Column("valid_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_state", sa.String(length=16), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("relation_id LIKE 'knowledge-relation:%'", name="ck_knowledge_relation_id_prefix"),
        sa.CheckConstraint("revision >= 1", name="ck_knowledge_relation_revision_positive"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_knowledge_relation_content_hash"),
        sa.CheckConstraint(
            "relation_kind IN ('supported_by', 'contradicts', 'clarifies', 'derived_from')",
            name="ck_knowledge_relation_kind",
        ),
        sa.CheckConstraint(
            "source_claim_id != target_claim_id OR source_claim_revision != target_claim_revision",
            name="ck_knowledge_relation_not_self",
        ),
        sa.CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR valid_start IS NULL OR "
            "valid_end IS NULL OR valid_start < valid_end",
            name="ck_knowledge_relation_valid_period",
        ),
        sa.CheckConstraint(
            "review_state IN ('candidate', 'approved', 'rejected', 'unresolved')",
            name="ck_knowledge_relation_review_state",
        ),
        sa.ForeignKeyConstraint(
            ["source_claim_id", "source_claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_relation_source_claim",
        ),
        sa.ForeignKeyConstraint(
            ["target_claim_id", "target_claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_relation_target_claim",
        ),
        sa.PrimaryKeyConstraint("relation_id", "revision", name="pk_knowledge_claim_relations"),
        sa.UniqueConstraint(
            "relation_id", "revision", "content_hash", name="uq_knowledge_relation_revision_hash"
        ),
    )
    op.create_index(
        "ix_knowledge_relation_source",
        "knowledge_claim_relations",
        ["source_claim_id", "source_claim_revision", "relation_kind"],
    )
    op.create_index(
        "ix_knowledge_relation_target",
        "knowledge_claim_relations",
        ["target_claim_id", "target_claim_revision", "relation_kind"],
    )
    op.create_index(
        "ix_knowledge_relation_review", "knowledge_claim_relations", ["review_state", "recorded_at"]
    )
    op.create_table(
        "knowledge_claim_relation_evidence",
        sa.Column("relation_id", sa.String(length=96), nullable=False),
        sa.Column("relation_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_observation_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("locator_page", sa.Integer(), nullable=True),
        sa.Column("locator_table", sa.String(length=256), nullable=True),
        sa.Column("locator_row", sa.Integer(), nullable=True),
        sa.Column("locator_section", sa.String(length=512), nullable=True),
        sa.Column("locator_field", sa.String(length=128), nullable=True),
        sa.Column("locator_record_key", sa.String(length=256), nullable=True),
        sa.Column("inferred", sa.Boolean(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_relation_evidence_ordinal"),
        sa.CheckConstraint("length(source_url) > 0", name="ck_knowledge_relation_evidence_url"),
        sa.CheckConstraint("locator_page IS NULL OR locator_page >= 1", name="ck_knowledge_relation_evidence_page"),
        sa.CheckConstraint("locator_row IS NULL OR locator_row >= 1", name="ck_knowledge_relation_evidence_row"),
        sa.ForeignKeyConstraint(
            ["relation_id", "relation_revision"],
            ["knowledge_claim_relations.relation_id", "knowledge_claim_relations.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_relation_evidence_revision",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["knowledge_source_observations.source_observation_id"],
            ondelete="RESTRICT",
            name="fk_knowledge_relation_evidence_observation",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_sha256"],
            ["source_snapshots.content_sha256"],
            ondelete="RESTRICT",
            name="fk_knowledge_relation_evidence_snapshot",
        ),
        sa.PrimaryKeyConstraint(
            "relation_id", "relation_revision", "ordinal", name="pk_knowledge_claim_relation_evidence"
        ),
    )
    op.create_index(
        "ix_knowledge_relation_evidence_observation",
        "knowledge_claim_relation_evidence",
        ["source_observation_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    relation_count = bind.execute(sa.text("SELECT COUNT(*) FROM knowledge_claim_relations")).scalar_one()
    if relation_count:
        raise RuntimeError("Refusing to downgrade typed knowledge relations containing data")
    op.drop_index("ix_knowledge_relation_evidence_observation", table_name="knowledge_claim_relation_evidence")
    op.drop_table("knowledge_claim_relation_evidence")
    op.drop_index("ix_knowledge_relation_review", table_name="knowledge_claim_relations")
    op.drop_index("ix_knowledge_relation_target", table_name="knowledge_claim_relations")
    op.drop_index("ix_knowledge_relation_source", table_name="knowledge_claim_relations")
    op.drop_table("knowledge_claim_relations")
    with op.batch_alter_table("policy_rule_relations") as batch:
        batch.drop_constraint("ck_policy_rule_relation_kind", type_="check")
        batch.create_check_constraint(
            "ck_policy_rule_relation_kind",
            "relation_kind IN ('exception_to', 'authorized_exception_to', 'overrides', 'supersedes', 'amends')",
        )
