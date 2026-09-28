"""Allow source-backed international olympiad team-member rights."""

from __future__ import annotations

from alembic import op

revision = "0035_benefit_team_member"
down_revision = "0034_admission_benefits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admission_benefit_rules") as batch_op:
        batch_op.drop_constraint("ck_benefit_rule_result_type", type_="check")
        batch_op.create_check_constraint(
            "ck_benefit_rule_result_type",
            "result_type IS NULL OR result_type IN ('winner', 'prize_winner', 'team_member')",
        )


def downgrade() -> None:
    with op.batch_alter_table("admission_benefit_rules") as batch_op:
        batch_op.drop_constraint("ck_benefit_rule_result_type", type_="check")
        batch_op.create_check_constraint(
            "ck_benefit_rule_result_type",
            "result_type IS NULL OR result_type IN ('winner', 'prize_winner')",
        )
