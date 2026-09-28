"""Persist exact content-addressed domain-owner revision references."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0051_policy_domain_owner_revision_hash"
down_revision = "0050_knowledge_manual_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("policy_rule_revisions", recreate="auto") as batch:
        batch.add_column(sa.Column("owner_revision_hash", sa.String(length=64), nullable=True))
        batch.drop_constraint("ck_policy_rule_schema_authority", type_="check")
        batch.create_check_constraint(
            "ck_policy_rule_schema_authority",
            "(schema_version = 'policy-rule.v1' AND family_id IS NULL AND authority_level IS NULL "
            "AND owner_revision_hash IS NULL) OR "
            "(schema_version = 'policy-rule.v2' AND family_id LIKE 'policy-family:%' AND "
            "authority_level IN ('federal_normative', 'regulator_normative', 'university_normative', 'unresolved') "
            "AND owner_revision_hash IS NULL) OR "
            "(schema_version = 'policy-rule.v3' AND family_id LIKE 'policy-family:%' AND "
            "authority_level IN ('federal_normative', 'regulator_normative', 'university_normative', 'unresolved') "
            "AND owner_revision_hash IS NOT NULL AND length(owner_revision_hash) = 64)",
        )
        batch.create_check_constraint(
            "ck_policy_rule_owner_revision_hash",
            "owner_revision_hash IS NULL OR length(owner_revision_hash) = 64",
        )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text("SELECT count(*) FROM policy_rule_revisions WHERE schema_version = 'policy-rule.v3'")
    ).scalar_one()
    if count:
        raise RuntimeError("Cannot downgrade exact owner-hash policy revisions")
    with op.batch_alter_table("policy_rule_revisions", recreate="auto") as batch:
        batch.drop_constraint("ck_policy_rule_owner_revision_hash", type_="check")
        batch.drop_constraint("ck_policy_rule_schema_authority", type_="check")
        batch.create_check_constraint(
            "ck_policy_rule_schema_authority",
            "(schema_version = 'policy-rule.v1' AND family_id IS NULL AND authority_level IS NULL) OR "
            "(schema_version = 'policy-rule.v2' AND family_id LIKE 'policy-family:%' AND "
            "authority_level IN ('federal_normative', 'regulator_normative', 'university_normative', 'unresolved'))",
        )
        batch.drop_column("owner_revision_hash")
