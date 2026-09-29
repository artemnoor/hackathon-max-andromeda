"""Add source-backed, as-known-at admission-cycle revisions."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0040_admission_cycle_revisions"
down_revision = "0039_knowledge_source_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admission_cycles",
        sa.Column("cycle_id", sa.String(length=96), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("university_id", sa.String(length=64), nullable=False),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(length=9), nullable=False),
        sa.Column("application_start", sa.Date(), nullable=True),
        sa.Column("application_end", sa.Date(), nullable=True),
        sa.Column("enrollment_start", sa.Date(), nullable=True),
        sa.Column("enrollment_end", sa.Date(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("approved_by_account_id", sa.String(length=128), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_reason", sa.String(length=512), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "cycle_id LIKE 'admission-cycle:%'", name="ck_admission_cycle_id_prefix"
        ),
        sa.CheckConstraint(
            "cycle_id = 'admission-cycle:' || replace(university_id, 'university:', '') || ':' || admission_year",
            name="ck_admission_cycle_id_matches_natural_key",
        ),
        sa.CheckConstraint(
            "admission_year BETWEEN 2000 AND 2100", name="ck_admission_cycle_admission_year"
        ),
        sa.CheckConstraint(
            "length(academic_year) = 9 AND substr(academic_year, 5, 1) = '/' "
            "AND CAST(substr(academic_year, 6, 4) AS INTEGER) = CAST(substr(academic_year, 1, 4) AS INTEGER) + 1",
            name="ck_admission_cycle_academic_year",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_admission_cycle_revision"),
        sa.CheckConstraint(
            "recorded_at >= approved_at", name="ck_admission_cycle_recorded_after_approval"
        ),
        sa.CheckConstraint(
            "state IN ('planned', 'published', 'application_open', 'enrollment_open', 'closed', 'cancelled', 'unknown')",
            name="ck_admission_cycle_state",
        ),
        sa.CheckConstraint(
            "(application_start IS NULL AND application_end IS NULL) OR "
            "(application_start IS NOT NULL AND application_end IS NOT NULL AND application_start <= application_end)",
            name="ck_admission_cycle_application_period",
        ),
        sa.CheckConstraint(
            "(enrollment_start IS NULL AND enrollment_end IS NULL) OR "
            "(enrollment_start IS NOT NULL AND enrollment_end IS NOT NULL AND enrollment_start <= enrollment_end)",
            name="ck_admission_cycle_enrollment_period",
        ),
        sa.CheckConstraint(
            "length(approval_reason) > 0", name="ck_admission_cycle_approval_reason"
        ),
        sa.ForeignKeyConstraint(
            ["university_id"], ["universities.id"], ondelete="RESTRICT",
            name="fk_admission_cycle_university",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_account_id"], ["accounts.account_id"], ondelete="RESTRICT",
            name="fk_admission_cycle_approver",
        ),
        sa.PrimaryKeyConstraint("cycle_id", "revision", name="pk_admission_cycles"),
        sa.UniqueConstraint(
            "university_id", "admission_year", "revision",
            name="uq_admission_cycle_university_year_revision",
        ),
    )
    op.create_index(
        "ix_admission_cycle_as_known",
        "admission_cycles",
        ["university_id", "admission_year", "recorded_at"],
    )
    op.create_table(
        "admission_cycle_evidence",
        sa.Column("cycle_id", sa.String(length=96), nullable=False),
        sa.Column("cycle_revision", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("ordinal >= 0", name="ck_admission_cycle_evidence_ordinal"),
        sa.CheckConstraint("length(source_url) > 0", name="ck_admission_cycle_evidence_url"),
        sa.CheckConstraint(
            "locator_page IS NULL OR locator_page >= 1",
            name="ck_admission_cycle_evidence_page",
        ),
        sa.CheckConstraint(
            "locator_row IS NULL OR locator_row >= 1",
            name="ck_admission_cycle_evidence_row",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id", "cycle_revision"],
            ["admission_cycles.cycle_id", "admission_cycles.revision"],
            ondelete="RESTRICT",
            name="fk_admission_cycle_evidence_revision",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["knowledge_source_observations.source_observation_id"],
            ondelete="RESTRICT",
            name="fk_admission_cycle_evidence_observation",
        ),
        sa.PrimaryKeyConstraint(
            "cycle_id", "cycle_revision", "ordinal", name="pk_admission_cycle_evidence"
        ),
    )
    op.create_index(
        "ix_admission_cycle_evidence_observation",
        "admission_cycle_evidence",
        ["source_observation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admission_cycle_evidence_observation", table_name="admission_cycle_evidence"
    )
    op.drop_table("admission_cycle_evidence")
    op.drop_index("ix_admission_cycle_as_known", table_name="admission_cycles")
    op.drop_table("admission_cycles")
