"""Add immutable source claim and change-event candidates."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0041_knowledge_claims_and_change_events"
down_revision = "0040_admission_cycle_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_claims",
        sa.Column("claim_id", sa.String(length=70), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_observation_id", sa.String(length=64), nullable=False),
        sa.Column("text_start_offset", sa.Integer(), nullable=False),
        sa.Column("text_end_offset", sa.Integer(), nullable=False),
        sa.Column("assertion_text", sa.Text(), nullable=False),
        sa.Column("assertion_text_sha256", sa.String(length=64), nullable=False),
        sa.Column("proposition_predicate", sa.String(length=96), nullable=True),
        sa.Column("proposition_subject_kind", sa.String(length=32), nullable=True),
        sa.Column("proposition_subject_id", sa.String(length=320), nullable=True),
        sa.Column("proposition_unit", sa.String(length=64), nullable=True),
        sa.Column("proposition_value_kind", sa.String(length=16), nullable=True),
        sa.Column("proposition_value_text", sa.Text(), nullable=True),
        sa.Column("proposition_value_decimal", sa.Numeric(16, 6), nullable=True),
        sa.Column("proposition_value_boolean", sa.Boolean(), nullable=True),
        sa.Column("proposition_value_date", sa.Date(), nullable=True),
        sa.Column("proposition_value_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposition_value_identifier", sa.String(length=320), nullable=True),
        sa.Column("claimed_stage", sa.String(length=32), nullable=False),
        sa.Column("review_state", sa.String(length=40), nullable=False),
        sa.Column("valid_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extraction_method", sa.String(length=32), nullable=False),
        sa.Column("extractor_id", sa.String(length=96), nullable=False),
        sa.Column("extractor_version", sa.String(length=64), nullable=False),
        sa.Column("extraction_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("claim_id LIKE 'claim:%'", name="ck_knowledge_claim_id_prefix"),
        sa.CheckConstraint("revision >= 1", name="ck_knowledge_claim_revision"),
        sa.CheckConstraint(
            "text_start_offset >= 0 AND text_start_offset < text_end_offset",
            name="ck_knowledge_claim_text_offsets",
        ),
        sa.CheckConstraint("length(assertion_text) > 0", name="ck_knowledge_claim_text"),
        sa.CheckConstraint(
            "length(assertion_text_sha256) = 64", name="ck_knowledge_claim_text_hash"
        ),
        sa.CheckConstraint(
            "(proposition_predicate IS NULL AND proposition_subject_kind IS NULL AND "
            "proposition_subject_id IS NULL AND proposition_unit IS NULL AND "
            "proposition_value_kind IS NULL AND proposition_value_text IS NULL AND "
            "proposition_value_decimal IS NULL AND proposition_value_boolean IS NULL AND "
            "proposition_value_date IS NULL AND proposition_value_datetime IS NULL AND "
            "proposition_value_identifier IS NULL) OR "
            "(proposition_predicate IS NOT NULL AND proposition_subject_kind IS NOT NULL AND "
            "proposition_value_kind IS NOT NULL AND ((proposition_value_kind = 'text' AND "
            "proposition_value_text IS NOT NULL AND proposition_value_decimal IS NULL AND "
            "proposition_value_boolean IS NULL AND proposition_value_date IS NULL AND "
            "proposition_value_datetime IS NULL AND proposition_value_identifier IS NULL) OR "
            "(proposition_value_kind = 'decimal' AND proposition_value_decimal IS NOT NULL AND "
            "proposition_value_text IS NULL AND proposition_value_boolean IS NULL AND "
            "proposition_value_date IS NULL AND proposition_value_datetime IS NULL AND "
            "proposition_value_identifier IS NULL) OR "
            "(proposition_value_kind = 'boolean' AND proposition_value_boolean IS NOT NULL AND "
            "proposition_value_text IS NULL AND proposition_value_decimal IS NULL AND "
            "proposition_value_date IS NULL AND proposition_value_datetime IS NULL AND "
            "proposition_value_identifier IS NULL) OR "
            "(proposition_value_kind = 'date' AND proposition_value_date IS NOT NULL AND "
            "proposition_value_text IS NULL AND proposition_value_decimal IS NULL AND "
            "proposition_value_boolean IS NULL AND proposition_value_datetime IS NULL AND "
            "proposition_value_identifier IS NULL) OR "
            "(proposition_value_kind = 'datetime' AND proposition_value_datetime IS NOT NULL AND "
            "proposition_value_text IS NULL AND proposition_value_decimal IS NULL AND "
            "proposition_value_boolean IS NULL AND proposition_value_date IS NULL AND "
            "proposition_value_identifier IS NULL) OR "
            "(proposition_value_kind = 'identifier' AND proposition_value_identifier IS NOT NULL AND "
            "proposition_value_text IS NULL AND proposition_value_decimal IS NULL AND "
            "proposition_value_boolean IS NULL AND proposition_value_date IS NULL AND "
            "proposition_value_datetime IS NULL)))",
            name="ck_knowledge_claim_proposition_value_shape",
        ),
        sa.CheckConstraint(
            "claimed_stage IN ('rumor', 'hypothesis', 'announced', 'proposal', 'draft', 'under_review', "
            "'adopted', 'published', 'future_effective', 'effective', 'superseded', 'repealed', "
            "'withdrawn', 'rejected', 'unknown')",
            name="ck_knowledge_claim_claimed_stage",
        ),
        sa.CheckConstraint(
            "review_state IN ('unreviewed', 'needs_review', 'accepted_as_source_assertion', 'rejected', 'unresolved')",
            name="ck_knowledge_claim_review_state",
        ),
        sa.CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR "
            "valid_start IS NOT NULL AND (valid_end IS NULL OR valid_start < valid_end)",
            name="ck_knowledge_claim_valid_period",
        ),
        sa.CheckConstraint(
            "effective_start IS NULL AND effective_end IS NULL OR "
            "effective_start IS NOT NULL AND (effective_end IS NULL OR effective_start < effective_end)",
            name="ck_knowledge_claim_effective_period",
        ),
        sa.CheckConstraint(
            "claimed_stage NOT IN ('future_effective', 'effective', 'superseded', 'repealed') "
            "OR effective_start IS NOT NULL",
            name="ck_knowledge_claim_stage_requires_effective_date",
        ),
        sa.CheckConstraint(
            "claimed_stage != 'future_effective' OR effective_start > recorded_at",
            name="ck_knowledge_claim_future_stage_after_recording",
        ),
        sa.CheckConstraint(
            "claimed_stage NOT IN ('effective', 'superseded', 'repealed') "
            "OR effective_start <= recorded_at",
            name="ck_knowledge_claim_active_stage_after_effective_time",
        ),
        sa.CheckConstraint(
            "extraction_method IN ('structured_document', 'deterministic_parser', 'manual', 'jev_suggestion')",
            name="ck_knowledge_claim_extraction_method",
        ),
        sa.CheckConstraint("length(extractor_id) > 0", name="ck_knowledge_claim_extractor_id"),
        sa.CheckConstraint(
            "length(extractor_version) > 0", name="ck_knowledge_claim_extractor_version"
        ),
        sa.CheckConstraint(
            "extraction_confidence IS NULL OR extraction_confidence BETWEEN 0 AND 1",
            name="ck_knowledge_claim_extraction_confidence",
        ),
        sa.CheckConstraint(
            "extraction_method != 'jev_suggestion' OR "
            "(extraction_confidence IS NOT NULL AND review_state IN ('unreviewed', 'needs_review'))",
            name="ck_knowledge_claim_jev_needs_review",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["knowledge_source_observations.source_observation_id"],
            ondelete="RESTRICT",
            name="fk_knowledge_claim_source_observation",
        ),
        sa.PrimaryKeyConstraint("claim_id", "revision", name="pk_knowledge_claims"),
    )
    op.create_index(
        "ix_knowledge_claims_observation",
        "knowledge_claims",
        ["source_observation_id", "text_start_offset"],
    )
    op.create_index(
        "ix_knowledge_claims_stage_review",
        "knowledge_claims",
        ["claimed_stage", "review_state", "recorded_at"],
    )
    op.create_index("ix_knowledge_claims_recorded_at", "knowledge_claims", ["recorded_at"])

    op.create_table(
        "knowledge_claim_evidence",
        sa.Column("claim_id", sa.String(length=70), nullable=False),
        sa.Column("claim_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("relationship", sa.String(length=24), nullable=False),
        sa.Column("source_observation_id", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("locator_page", sa.Integer(), nullable=True),
        sa.Column("locator_table", sa.String(length=256), nullable=True),
        sa.Column("locator_row", sa.Integer(), nullable=True),
        sa.Column("locator_section", sa.String(length=512), nullable=True),
        sa.Column("locator_field", sa.String(length=128), nullable=True),
        sa.Column("locator_record_key", sa.String(length=256), nullable=True),
        sa.Column("inferred", sa.Boolean(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_claim_evidence_ordinal"),
        sa.CheckConstraint(
            "relationship IN ('originates_from', 'supports', 'contradicts', 'qualifies')",
            name="ck_knowledge_claim_evidence_relationship",
        ),
        sa.CheckConstraint("length(source_url) > 0", name="ck_knowledge_claim_evidence_url"),
        sa.CheckConstraint(
            "locator_page IS NULL OR locator_page >= 1", name="ck_knowledge_claim_evidence_page"
        ),
        sa.CheckConstraint(
            "locator_row IS NULL OR locator_row >= 1", name="ck_knowledge_claim_evidence_row"
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_claim_evidence_claim",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["knowledge_source_observations.source_observation_id"],
            ondelete="RESTRICT",
            name="fk_knowledge_claim_evidence_observation",
        ),
        sa.PrimaryKeyConstraint(
            "claim_id", "claim_revision", "ordinal", name="pk_knowledge_claim_evidence"
        ),
    )
    op.create_index(
        "ix_knowledge_claim_evidence_observation",
        "knowledge_claim_evidence",
        ["source_observation_id"],
    )

    op.create_table(
        "knowledge_change_events",
        sa.Column("change_event_id", sa.String(length=78), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("primary_source_observation_id", sa.String(length=64), nullable=False),
        sa.Column("event_kind", sa.String(length=32), nullable=False),
        sa.Column("review_state", sa.String(length=32), nullable=False),
        sa.Column("valid_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "change_event_id LIKE 'change-event:%'", name="ck_knowledge_change_event_id_prefix"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_knowledge_change_event_revision"),
        sa.CheckConstraint(
            "event_kind IN ('hypothesis_reported', 'announcement_published', 'proposal_published', "
            "'draft_published', 'decision_adopted', 'document_published', 'rule_effective', "
            "'rule_amended', 'rule_superseded', 'rule_repealed', 'proposal_withdrawn', "
            "'proposal_rejected', 'unknown')",
            name="ck_knowledge_change_event_kind",
        ),
        sa.CheckConstraint(
            "review_state IN ('needs_review', 'accepted_as_source_event', 'rejected', 'unresolved')",
            name="ck_knowledge_change_event_review_state",
        ),
        sa.CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR "
            "valid_start IS NOT NULL AND (valid_end IS NULL OR valid_start < valid_end)",
            name="ck_knowledge_change_event_valid_period",
        ),
        sa.CheckConstraint(
            "effective_start IS NULL AND effective_end IS NULL OR "
            "effective_start IS NOT NULL AND (effective_end IS NULL OR effective_start < effective_end)",
            name="ck_knowledge_change_event_effective_period",
        ),
        sa.CheckConstraint(
            "event_kind != 'announcement_published' OR announced_at IS NOT NULL",
            name="ck_knowledge_change_event_announcement_time",
        ),
        sa.CheckConstraint(
            "event_kind NOT IN ('proposal_published', 'draft_published', 'document_published') OR published_at IS NOT NULL",
            name="ck_knowledge_change_event_publication_time",
        ),
        sa.CheckConstraint(
            "event_kind != 'decision_adopted' OR adopted_at IS NOT NULL",
            name="ck_knowledge_change_event_adoption_time",
        ),
        sa.CheckConstraint(
            "event_kind != 'rule_effective' OR effective_start IS NOT NULL",
            name="ck_knowledge_change_event_effective_time",
        ),
        sa.PrimaryKeyConstraint(
            "change_event_id", "revision", name="pk_knowledge_change_events"
        ),
        sa.ForeignKeyConstraint(
            ["primary_source_observation_id"],
            ["knowledge_source_observations.source_observation_id"],
            ondelete="RESTRICT",
            name="fk_knowledge_change_event_primary_observation",
        ),
    )
    op.create_index(
        "ix_knowledge_change_events_review",
        "knowledge_change_events",
        ["review_state", "recorded_at"],
    )

    op.create_table(
        "knowledge_change_event_claims",
        sa.Column("change_event_id", sa.String(length=78), nullable=False),
        sa.Column("event_revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.String(length=70), nullable=False),
        sa.Column("claim_revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_change_event_claim_ordinal"),
        sa.ForeignKeyConstraint(
            ["change_event_id", "event_revision"],
            ["knowledge_change_events.change_event_id", "knowledge_change_events.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_change_event_claim_event",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_change_event_claim_revision",
        ),
        sa.PrimaryKeyConstraint(
            "change_event_id", "event_revision", "ordinal",
            name="pk_knowledge_change_event_claims",
        ),
        sa.UniqueConstraint(
            "change_event_id", "event_revision", "claim_id", "claim_revision",
            name="uq_knowledge_change_event_claim_ref",
        ),
    )
    op.create_index(
        "ix_knowledge_change_event_claim_claim",
        "knowledge_change_event_claims",
        ["claim_id", "claim_revision"],
    )

    op.create_table(
        "knowledge_change_event_evidence",
        sa.Column("change_event_id", sa.String(length=78), nullable=False),
        sa.Column("event_revision", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_change_event_evidence_ordinal"),
        sa.CheckConstraint(
            "length(source_url) > 0", name="ck_knowledge_change_event_evidence_url"
        ),
        sa.CheckConstraint(
            "locator_page IS NULL OR locator_page >= 1",
            name="ck_knowledge_change_event_evidence_page",
        ),
        sa.CheckConstraint(
            "locator_row IS NULL OR locator_row >= 1",
            name="ck_knowledge_change_event_evidence_row",
        ),
        sa.ForeignKeyConstraint(
            ["change_event_id", "event_revision"],
            ["knowledge_change_events.change_event_id", "knowledge_change_events.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_change_event_evidence_event",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["knowledge_source_observations.source_observation_id"],
            ondelete="RESTRICT",
            name="fk_knowledge_change_event_evidence_observation",
        ),
        sa.PrimaryKeyConstraint(
            "change_event_id", "event_revision", "ordinal",
            name="pk_knowledge_change_event_evidence",
        ),
    )
    op.create_index(
        "ix_knowledge_change_event_evidence_observation",
        "knowledge_change_event_evidence",
        ["source_observation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_change_event_evidence_observation",
        table_name="knowledge_change_event_evidence",
    )
    op.drop_table("knowledge_change_event_evidence")
    op.drop_index(
        "ix_knowledge_change_event_claim_claim", table_name="knowledge_change_event_claims"
    )
    op.drop_table("knowledge_change_event_claims")
    op.drop_index("ix_knowledge_change_events_review", table_name="knowledge_change_events")
    op.drop_table("knowledge_change_events")
    op.drop_index(
        "ix_knowledge_claim_evidence_observation", table_name="knowledge_claim_evidence"
    )
    op.drop_table("knowledge_claim_evidence")
    op.drop_index("ix_knowledge_claims_recorded_at", table_name="knowledge_claims")
    op.drop_index("ix_knowledge_claims_stage_review", table_name="knowledge_claims")
    op.drop_index("ix_knowledge_claims_observation", table_name="knowledge_claims")
    op.drop_table("knowledge_claims")
