"""Persist applicant category for source-defined Olympiad thresholds."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0037_confirmation_applicant_category"
down_revision = "0036_admission_benefit_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admission_benefit_rule_subjects") as batch_op:
        batch_op.add_column(sa.Column("applicant_category", sa.String(length=64), nullable=True))
        batch_op.create_check_constraint(
            "ck_benefit_rule_subject_applicant_category",
            "applicant_category IS NULL OR applicant_category IN ('standard', 'territorial_exception', 'unknown')",
        )


def downgrade() -> None:
    with op.batch_alter_table("admission_benefit_rule_subjects") as batch_op:
        batch_op.drop_constraint(
            "ck_benefit_rule_subject_applicant_category", type_="check"
        )
        batch_op.drop_column("applicant_category")
