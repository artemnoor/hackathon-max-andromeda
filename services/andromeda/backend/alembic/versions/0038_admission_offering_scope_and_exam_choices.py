"""Persist optional admission campus and source-defined choice groups."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0038_admission_offering_scope_and_exam_choices"
down_revision = "0037_confirmation_applicant_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admission_benefit_rule_scopes") as batch_op:
        batch_op.drop_constraint("ck_benefit_scope_target_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_benefit_scope_target_kind",
            "target_kind IN ('direction', 'program', 'nps', 'education_level', 'campus')",
        )

    with op.batch_alter_table("admission_offerings") as batch_op:
        batch_op.add_column(sa.Column("campus_id", sa.String(length=96), nullable=True))
        batch_op.drop_constraint("uq_admission_offering_identity", type_="unique")

    with op.batch_alter_table("admission_exam_requirements") as batch_op:
        batch_op.add_column(sa.Column("choice_group_id", sa.String(length=96), nullable=True))
        batch_op.add_column(sa.Column("choice_group_min", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("choice_group_max", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_admission_exam_choice_group_id",
            "choice_group_id IS NULL OR length(choice_group_id) > 0",
        )
        batch_op.create_check_constraint(
            "ck_admission_exam_choice_group_min",
            "choice_group_min IS NULL OR (choice_group_min >= 1 AND choice_group_min <= 20)",
        )
        batch_op.create_check_constraint(
            "ck_admission_exam_choice_group_max",
            "choice_group_max IS NULL OR (choice_group_max >= 1 AND choice_group_max <= 20)",
        )
        batch_op.create_check_constraint(
            "ck_admission_exam_choice_group_order",
            "choice_group_min IS NULL OR choice_group_max IS NULL OR choice_group_min <= choice_group_max",
        )
        batch_op.create_check_constraint(
            "ck_admission_exam_choice_group_flag",
            "choice_group_id IS NULL OR is_choice",
        )

    op.create_index(
        "uq_admission_offering_identity_without_campus",
        "admission_offerings",
        ["program_id", "admission_year", "study_form", "funding_type", "scope"],
        unique=True,
        sqlite_where=sa.text("campus_id IS NULL"),
        postgresql_where=sa.text("campus_id IS NULL"),
    )
    op.create_index(
        "uq_admission_offering_identity_by_campus",
        "admission_offerings",
        ["program_id", "admission_year", "study_form", "funding_type", "scope", "campus_id"],
        unique=True,
        sqlite_where=sa.text("campus_id IS NOT NULL"),
        postgresql_where=sa.text("campus_id IS NOT NULL"),
    )
    op.create_index(
        "ix_admission_offerings_campus_year",
        "admission_offerings",
        ["campus_id", "admission_year"],
    )
    op.create_index(
        "ix_admission_exams_choice_group",
        "admission_exam_requirements",
        ["offering_id", "choice_group_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    campus_scope = bind.execute(
        sa.text(
            "SELECT rule_id FROM admission_benefit_rule_scopes "
            "WHERE target_kind = 'campus' LIMIT 1"
        )
    ).first()
    if campus_scope is not None:
        raise RuntimeError(
            "Cannot downgrade campus-scoped admission benefit rules without losing applicability"
        )
    duplicate_campuses = bind.execute(
        sa.text(
            "SELECT program_id, admission_year, study_form, funding_type, scope "
            "FROM admission_offerings "
            "GROUP BY program_id, admission_year, study_form, funding_type, scope "
            "HAVING COUNT(*) > 1"
        )
    ).first()
    if duplicate_campuses is not None:
        raise RuntimeError(
            "Cannot downgrade admission campus identity while multiple campus offerings exist"
        )

    with op.batch_alter_table("admission_benefit_rule_scopes") as batch_op:
        batch_op.drop_constraint("ck_benefit_scope_target_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_benefit_scope_target_kind",
            "target_kind IN ('direction', 'program', 'nps', 'education_level')",
        )

    op.drop_index("ix_admission_exams_choice_group", table_name="admission_exam_requirements")
    op.drop_index("ix_admission_offerings_campus_year", table_name="admission_offerings")
    op.drop_index("uq_admission_offering_identity_by_campus", table_name="admission_offerings")
    op.drop_index("uq_admission_offering_identity_without_campus", table_name="admission_offerings")

    with op.batch_alter_table("admission_exam_requirements") as batch_op:
        batch_op.drop_constraint("ck_admission_exam_choice_group_flag", type_="check")
        batch_op.drop_constraint("ck_admission_exam_choice_group_order", type_="check")
        batch_op.drop_constraint("ck_admission_exam_choice_group_max", type_="check")
        batch_op.drop_constraint("ck_admission_exam_choice_group_min", type_="check")
        batch_op.drop_constraint("ck_admission_exam_choice_group_id", type_="check")
        batch_op.drop_column("choice_group_max")
        batch_op.drop_column("choice_group_min")
        batch_op.drop_column("choice_group_id")

    with op.batch_alter_table("admission_offerings") as batch_op:
        batch_op.drop_column("campus_id")
        batch_op.create_unique_constraint(
            "uq_admission_offering_identity",
            ["program_id", "admission_year", "study_form", "funding_type", "scope"],
        )
