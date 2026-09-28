"""Persist source-backed admission benefits and individual achievements."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0034_admission_benefits"
down_revision = "0033_projection_runs"
branch_labels = None
depends_on = None


_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _provenance_columns() -> tuple[sa.Column, ...]:
    """Shared source/provenance columns for canonical benefit facts."""

    return (
        sa.Column("source_kind", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("source_run_id", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_title", sa.String(length=512), nullable=False),
        sa.Column("document_kind", sa.String(length=128), nullable=False),
        sa.Column("appendix_number", sa.String(length=32), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_table", sa.String(length=256), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("source_section", sa.String(length=512), nullable=True),
        sa.Column("source_locator", sa.String(length=512), nullable=True),
        sa.Column("parser_version", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
    )


def _source_foreign_keys() -> tuple[sa.ForeignKeyConstraint, ...]:
    return (
        sa.ForeignKeyConstraint(["source_snapshot_hash"], ["source_snapshots.content_sha256"]),
        sa.ForeignKeyConstraint(["source_run_id"], ["ingest_runs.id"]),
    )


def upgrade() -> None:
    op.create_table(
        "admission_benefit_olympiads",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("official_name", sa.String(length=512), nullable=False),
        sa.Column("organizer", sa.String(length=512), nullable=True),
        sa.Column("rsosh_level", sa.Integer(), nullable=True),
        *_provenance_columns(),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "admission_year", "source_snapshot_hash"),
        *_source_foreign_keys(),
        sa.CheckConstraint("admission_year >= 2000 AND admission_year <= 2100", name="ck_benefit_olympiad_year"),
        sa.CheckConstraint("rsosh_level IS NULL OR rsosh_level BETWEEN 1 AND 3", name="ck_benefit_olympiad_rsosh_level"),
        sa.CheckConstraint("status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')", name="ck_benefit_olympiad_status"),
        sa.CheckConstraint("length(official_name) > 0", name="ck_benefit_olympiad_name"),
    )
    op.create_index(
        "ix_benefit_olympiads_name_year",
        "admission_benefit_olympiads",
        ["official_name", "admission_year"],
    )
    op.create_index(
        "ix_benefit_olympiads_source_hash",
        "admission_benefit_olympiads",
        ["source_snapshot_hash", "status"],
    )

    op.create_table(
        "admission_benefit_olympiad_profiles",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("olympiad_id", sa.String(length=160), nullable=False),
        sa.Column("olympiad_source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("profile_name", sa.String(length=512), nullable=False),
        *_provenance_columns(),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "admission_year", "source_snapshot_hash"),
        sa.ForeignKeyConstraint(
            ["olympiad_id", "admission_year", "olympiad_source_snapshot_hash"],
            [
                "admission_benefit_olympiads.id",
                "admission_benefit_olympiads.admission_year",
                "admission_benefit_olympiads.source_snapshot_hash",
            ],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("olympiad_id", "admission_year", "profile_name", "source_snapshot_hash", name="uq_benefit_profile_name"),
        *_source_foreign_keys(),
        sa.CheckConstraint("admission_year >= 2000 AND admission_year <= 2100", name="ck_benefit_profile_year"),
        sa.CheckConstraint("status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')", name="ck_benefit_profile_status"),
    )
    op.create_index(
        "ix_benefit_profiles_olympiad_year",
        "admission_benefit_olympiad_profiles",
        ["olympiad_id", "admission_year", "status"],
    )

    op.create_table(
        "admission_benefit_profile_subjects",
        sa.Column("profile_id", sa.String(length=160), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("profile_source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("subject_index", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("source_text", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id", "admission_year", "profile_source_snapshot_hash"],
            ["admission_benefit_olympiad_profiles.id", "admission_benefit_olympiad_profiles.admission_year", "admission_benefit_olympiad_profiles.source_snapshot_hash"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("profile_id", "admission_year", "profile_source_snapshot_hash", "subject_index"),
        sa.CheckConstraint("subject_index >= 0", name="ck_benefit_profile_subject_index"),
    )
    op.create_index(
        "ix_benefit_profile_subjects_subject",
        "admission_benefit_profile_subjects",
        ["subject", "admission_year"],
    )

    op.create_table(
        "admission_benefit_rules",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.Column("education_level", sa.String(length=32), nullable=True),
        sa.Column("route", sa.String(length=32), nullable=False),
        sa.Column("benefit_type", sa.String(length=40), nullable=False),
        sa.Column("olympiad_id", sa.String(length=160), nullable=True),
        sa.Column("olympiad_profile_id", sa.String(length=160), nullable=True),
        sa.Column("result_type", sa.String(length=32), nullable=True),
        sa.Column("scope_mode", sa.String(length=32), nullable=False),
        sa.Column("scope_original_text", sa.String(length=2_000), nullable=False),
        sa.Column("confirmation_requirement", sa.String(length=32), nullable=False),
        sa.Column("valid_from_result_year", sa.Integer(), nullable=True),
        sa.Column("valid_until_result_year", sa.Integer(), nullable=True),
        sa.Column("max_age_years", sa.Integer(), nullable=True),
        sa.Column("validity_source_text", sa.String(length=512), nullable=False),
        sa.Column("target_subject", sa.String(length=256), nullable=True),
        sa.Column("points", sa.Numeric(5, 2), nullable=True),
        sa.Column("conditions_json", _JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_text", sa.String(length=10_000), nullable=False),
        *_provenance_columns(),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("conflict_group", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "admission_year", "source_snapshot_hash"),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"]),
        *_source_foreign_keys(),
        sa.CheckConstraint("admission_year >= 2000 AND admission_year <= 2100", name="ck_benefit_rule_year"),
        sa.CheckConstraint("route IN ('olympiad', 'vosh', 'international', 'special_right', 'preferential_right', 'special_quota', 'separate_quota', 'targeted', 'other')", name="ck_benefit_rule_route"),
        sa.CheckConstraint("scope_mode IN ('all', 'only', 'all_except')", name="ck_benefit_rule_scope_mode"),
        sa.CheckConstraint("confirmation_requirement IN ('required', 'not_required', 'unknown')", name="ck_benefit_rule_confirmation"),
        sa.CheckConstraint("result_type IS NULL OR result_type IN ('winner', 'prize_winner')", name="ck_benefit_rule_result_type"),
        sa.CheckConstraint("points IS NULL OR (points >= 0 AND points <= 100)", name="ck_benefit_rule_points"),
        sa.CheckConstraint("valid_from_result_year IS NULL OR valid_from_result_year >= 2000", name="ck_benefit_rule_valid_from"),
        sa.CheckConstraint("valid_until_result_year IS NULL OR valid_until_result_year >= 2000", name="ck_benefit_rule_valid_until"),
        sa.CheckConstraint("max_age_years IS NULL OR max_age_years >= 0", name="ck_benefit_rule_max_age"),
        sa.CheckConstraint("status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')", name="ck_benefit_rule_status"),
    )
    op.create_index(
        "ix_benefit_rules_university_year_active",
        "admission_benefit_rules",
        ["university_id", "admission_year", "education_level", "benefit_type", "status"],
    )
    op.create_index(
        "ix_benefit_rules_olympiad_result",
        "admission_benefit_rules",
        ["olympiad_id", "olympiad_profile_id", "result_type", "admission_year", "status"],
    )
    op.create_index(
        "ix_benefit_rules_source_refresh",
        "admission_benefit_rules",
        ["source_snapshot_hash", "source_run_id", "status"],
    )
    op.create_index(
        "ix_benefit_rules_conflict_group",
        "admission_benefit_rules",
        ["conflict_group", "status"],
    )

    op.create_table(
        "admission_benefit_rule_scopes",
        sa.Column("rule_id", sa.String(length=160), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("rule_source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("target_index", sa.Integer(), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_value", sa.String(length=256), nullable=False),
        sa.Column("original_text", sa.String(length=512), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(
            ["rule_id", "admission_year", "rule_source_snapshot_hash"],
            ["admission_benefit_rules.id", "admission_benefit_rules.admission_year", "admission_benefit_rules.source_snapshot_hash"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("rule_id", "admission_year", "rule_source_snapshot_hash", "target_index"),
        sa.CheckConstraint("target_index >= 0", name="ck_benefit_scope_target_index"),
        sa.CheckConstraint("target_kind IN ('direction', 'program', 'nps', 'education_level')", name="ck_benefit_scope_target_kind"),
        sa.CheckConstraint("resolution IN ('resolved', 'unresolved')", name="ck_benefit_scope_resolution"),
    )
    op.create_index(
        "ix_benefit_scope_target_lookup",
        "admission_benefit_rule_scopes",
        ["target_kind", "target_value", "admission_year", "excluded"],
    )

    op.create_table(
        "admission_benefit_rule_subjects",
        sa.Column("rule_id", sa.String(length=160), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("rule_source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("subject_index", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("minimum_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("exam_kind", sa.String(length=32), nullable=False),
        sa.Column("source_text", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_id", "admission_year", "rule_source_snapshot_hash"],
            ["admission_benefit_rules.id", "admission_benefit_rules.admission_year", "admission_benefit_rules.source_snapshot_hash"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("rule_id", "admission_year", "rule_source_snapshot_hash", "subject_index"),
        sa.CheckConstraint("subject_index >= 0", name="ck_benefit_rule_subject_index"),
        sa.CheckConstraint("minimum_score IS NULL OR (minimum_score >= 0 AND minimum_score <= 100)", name="ck_benefit_rule_subject_minimum"),
        sa.CheckConstraint("exam_kind IN ('ege', 'internal_exam', 'other', 'unknown')", name="ck_benefit_rule_subject_exam_kind"),
    )
    op.create_index(
        "ix_benefit_rule_subjects_subject",
        "admission_benefit_rule_subjects",
        ["subject", "admission_year"],
    )

    op.create_table(
        "individual_achievement_policies",
        sa.Column("id", sa.String(length=256), nullable=False),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("education_level", sa.String(length=32), nullable=False),
        sa.Column("global_max_points", sa.Numeric(5, 2), nullable=True),
        sa.Column("default_combination_policy", sa.String(length=32), nullable=False),
        sa.Column("source_text", sa.String(length=10_000), nullable=False),
        *_provenance_columns(),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("conflict_group", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "source_snapshot_hash"),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"]),
        *_source_foreign_keys(),
        sa.UniqueConstraint("university_id", "admission_year", "education_level", "source_snapshot_hash", name="uq_individual_achievement_policy_scope"),
        sa.CheckConstraint("admission_year >= 2000 AND admission_year <= 2100", name="ck_achievement_policy_year"),
        sa.CheckConstraint("global_max_points IS NULL OR (global_max_points >= 0 AND global_max_points <= 100)", name="ck_achievement_policy_global_max"),
        sa.CheckConstraint("default_combination_policy IN ('additive', 'max_only', 'mutually_exclusive', 'not_combinable', 'unknown')", name="ck_achievement_policy_combination"),
        sa.CheckConstraint("status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')", name="ck_achievement_policy_status"),
    )
    op.create_index(
        "ix_achievement_policies_university_year",
        "individual_achievement_policies",
        ["university_id", "admission_year", "education_level", "status"],
    )

    op.create_table(
        "individual_achievement_rules",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.String(length=256), nullable=False),
        sa.Column("policy_source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.Column("education_level", sa.String(length=32), nullable=True),
        sa.Column("achievement_code", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=256), nullable=False),
        sa.Column("official_name", sa.String(length=512), nullable=False),
        sa.Column("description", sa.String(length=10_000), nullable=True),
        sa.Column("points", sa.Numeric(5, 2), nullable=False),
        sa.Column("category_cap", sa.Numeric(5, 2), nullable=True),
        sa.Column("combination_group", sa.String(length=256), nullable=True),
        sa.Column("combination_policy", sa.String(length=32), nullable=False),
        sa.Column("required_document", sa.String(length=2_000), nullable=True),
        sa.Column("conditions_json", _JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_text", sa.String(length=10_000), nullable=False),
        *_provenance_columns(),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("conflict_group", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", "admission_year", "source_snapshot_hash"),
        sa.ForeignKeyConstraint(
            ["policy_id", "policy_source_snapshot_hash"],
            ["individual_achievement_policies.id", "individual_achievement_policies.source_snapshot_hash"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"]),
        *_source_foreign_keys(),
        sa.CheckConstraint("admission_year >= 2000 AND admission_year <= 2100", name="ck_achievement_rule_year"),
        sa.CheckConstraint("points >= 0 AND points <= 100", name="ck_achievement_rule_points"),
        sa.CheckConstraint("category_cap IS NULL OR (category_cap >= 0 AND category_cap <= 100)", name="ck_achievement_rule_category_cap"),
        sa.CheckConstraint("combination_policy IN ('additive', 'max_only', 'mutually_exclusive', 'not_combinable', 'unknown')", name="ck_achievement_rule_combination"),
        sa.CheckConstraint("status IN ('active', 'stale', 'review_required', 'conflict', 'unresolved')", name="ck_achievement_rule_status"),
    )
    op.create_index(
        "ix_achievement_rules_lookup",
        "individual_achievement_rules",
        ["university_id", "admission_year", "education_level", "achievement_code", "status"],
    )
    op.create_index(
        "ix_achievement_rules_source_refresh",
        "individual_achievement_rules",
        ["source_snapshot_hash", "source_run_id", "status"],
    )
    op.create_index(
        "ix_achievement_rules_combination",
        "individual_achievement_rules",
        ["combination_group", "combination_policy", "admission_year"],
    )


def downgrade() -> None:
    op.drop_index("ix_achievement_rules_combination", table_name="individual_achievement_rules")
    op.drop_index("ix_achievement_rules_source_refresh", table_name="individual_achievement_rules")
    op.drop_index("ix_achievement_rules_lookup", table_name="individual_achievement_rules")
    op.drop_table("individual_achievement_rules")
    op.drop_index("ix_achievement_policies_university_year", table_name="individual_achievement_policies")
    op.drop_table("individual_achievement_policies")
    op.drop_index("ix_benefit_rule_subjects_subject", table_name="admission_benefit_rule_subjects")
    op.drop_table("admission_benefit_rule_subjects")
    op.drop_index("ix_benefit_scope_target_lookup", table_name="admission_benefit_rule_scopes")
    op.drop_table("admission_benefit_rule_scopes")
    op.drop_index("ix_benefit_rules_conflict_group", table_name="admission_benefit_rules")
    op.drop_index("ix_benefit_rules_source_refresh", table_name="admission_benefit_rules")
    op.drop_index("ix_benefit_rules_olympiad_result", table_name="admission_benefit_rules")
    op.drop_index("ix_benefit_rules_university_year_active", table_name="admission_benefit_rules")
    op.drop_table("admission_benefit_rules")
    op.drop_index("ix_benefit_profile_subjects_subject", table_name="admission_benefit_profile_subjects")
    op.drop_table("admission_benefit_profile_subjects")
    op.drop_index("ix_benefit_profiles_olympiad_year", table_name="admission_benefit_olympiad_profiles")
    op.drop_table("admission_benefit_olympiad_profiles")
    op.drop_index("ix_benefit_olympiads_source_hash", table_name="admission_benefit_olympiads")
    op.drop_index("ix_benefit_olympiads_name_year", table_name="admission_benefit_olympiads")
    op.drop_table("admission_benefit_olympiads")
