"""Add independent legal authority and source-backed rule relations."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0045_policy_authority_relations"
down_revision = "0044_policy_selector_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("policy_rule_revisions", recreate="auto") as batch:
        batch.add_column(sa.Column("family_id", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("authority_level", sa.String(length=40), nullable=True))
        batch.drop_constraint("ck_policy_rule_schema_version", type_="check")
        batch.create_check_constraint(
            "ck_policy_rule_schema_authority",
            "(schema_version = 'policy-rule.v1' AND family_id IS NULL AND authority_level IS NULL) OR "
            "(schema_version = 'policy-rule.v2' AND family_id LIKE 'policy-family:%' AND "
            "authority_level IN ('federal_normative', 'regulator_normative', 'university_normative', 'unresolved'))",
        )
        batch.create_unique_constraint(
            "uq_policy_rule_revision_hash",
            ["rule_id", "revision", "content_hash"],
        )
    op.create_table(
        "policy_rule_relations",
        sa.Column("rule_id", sa.String(length=140), nullable=False),
        sa.Column("rule_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("relation_kind", sa.String(length=32), nullable=False),
        sa.Column("target_rule_id", sa.String(length=140), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("target_hash", sa.String(length=64), nullable=False),
        sa.Column("claim_ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_policy_rule_relation_ordinal"),
        sa.CheckConstraint("claim_ordinal >= 0", name="ck_policy_rule_relation_claim_ordinal"),
        sa.CheckConstraint(
            "evidence_ordinal >= 0", name="ck_policy_rule_relation_evidence_ordinal"
        ),
        sa.CheckConstraint("length(target_hash) = 64", name="ck_policy_rule_relation_target_hash"),
        sa.CheckConstraint(
            "(rule_id != target_rule_id) OR (rule_revision != target_revision)",
            name="ck_policy_rule_relation_not_self",
        ),
        sa.CheckConstraint(
            "relation_kind IN ('exception_to', 'authorized_exception_to', 'overrides', 'supersedes', 'amends')",
            name="ck_policy_rule_relation_kind",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id", "rule_revision"],
            ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision"],
            ondelete="RESTRICT",
            name="fk_policy_rule_relation_source",
        ),
        sa.ForeignKeyConstraint(
            ["target_rule_id", "target_revision", "target_hash"],
            [
                "policy_rule_revisions.rule_id",
                "policy_rule_revisions.revision",
                "policy_rule_revisions.content_hash",
            ],
            ondelete="RESTRICT",
            name="fk_policy_rule_relation_target_hash",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id", "rule_revision", "claim_ordinal"],
            [
                "policy_rule_revision_claims.rule_id",
                "policy_rule_revision_claims.rule_revision",
                "policy_rule_revision_claims.ordinal",
            ],
            ondelete="RESTRICT",
            name="fk_policy_rule_relation_claim",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id", "rule_revision", "evidence_ordinal"],
            [
                "policy_rule_revision_evidence.rule_id",
                "policy_rule_revision_evidence.rule_revision",
                "policy_rule_revision_evidence.ordinal",
            ],
            ondelete="RESTRICT",
            name="fk_policy_rule_relation_evidence",
        ),
        sa.PrimaryKeyConstraint(
            "rule_id", "rule_revision", "ordinal", name="pk_policy_rule_relations"
        ),
    )
    op.create_index(
        "ix_policy_rule_relation_target",
        "policy_rule_relations",
        ["target_rule_id", "target_revision"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT count(*) FROM policy_rule_revisions WHERE schema_version != 'policy-rule.v1'")
    ).scalar_one():
        raise RuntimeError("Cannot downgrade policy-rule.v2 rows without discarding authority and relations")
    op.drop_index("ix_policy_rule_relation_target", table_name="policy_rule_relations")
    op.drop_table("policy_rule_relations")
    with op.batch_alter_table("policy_rule_revisions", recreate="auto") as batch:
        batch.drop_constraint("uq_policy_rule_revision_hash", type_="unique")
        batch.drop_constraint("ck_policy_rule_schema_authority", type_="check")
        batch.create_check_constraint(
            "ck_policy_rule_schema_version", "schema_version = 'policy-rule.v1'"
        )
        batch.drop_column("authority_level")
        batch.drop_column("family_id")
