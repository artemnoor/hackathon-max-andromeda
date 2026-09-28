"""Add approved knowledge source registry and capture observations."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0039_knowledge_source_registry"
down_revision = "0038_admission_offering_scope_and_exam_choices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("issuer_id", sa.String(length=128), nullable=False),
        sa.Column("jurisdiction", sa.String(length=32), nullable=False),
        sa.Column("identity_key", sa.String(length=96), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_id LIKE 'source:%'", name="ck_knowledge_source_id_prefix"),
        sa.CheckConstraint("issuer_id LIKE 'issuer:%'", name="ck_knowledge_source_issuer_prefix"),
        sa.CheckConstraint(
            "jurisdiction IN ('federal', 'regional', 'university', 'international', 'unknown')",
            name="ck_knowledge_source_jurisdiction",
        ),
        sa.CheckConstraint("length(identity_key) > 0", name="ck_knowledge_source_identity_key"),
        sa.CheckConstraint("length(display_name) > 0", name="ck_knowledge_source_display_name"),
        sa.PrimaryKeyConstraint("source_id", name="pk_knowledge_sources"),
        sa.UniqueConstraint(
            "jurisdiction", "issuer_id", "identity_key", name="uq_knowledge_source_identity"
        ),
    )
    op.create_table(
        "knowledge_source_registry_revisions",
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("reliability_tier", sa.String(length=40), nullable=False),
        sa.Column("adapter_id", sa.String(length=96), nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("start_url", sa.Text(), nullable=False),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("freshness_budget_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("approved_by_account_id", sa.String(length=128), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_reason", sa.String(length=512), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_knowledge_source_registry_revision_positive"),
        sa.CheckConstraint(
            "source_kind IN ('normative_document', 'ministry_publication', 'university_admission_rules', "
            "'university_order', 'official_appendix', 'official_news', 'official_feed', 'official_api')",
            name="ck_knowledge_source_kind",
        ),
        sa.CheckConstraint(
            "reliability_tier IN ('primary_normative', 'official_issuer', 'official_university', "
            "'trusted_secondary', 'unverified_secondary', 'community', 'user_supplied', 'unknown')",
            name="ck_knowledge_source_reliability_tier",
        ),
        sa.CheckConstraint("length(adapter_id) > 0", name="ck_knowledge_source_adapter_id"),
        sa.CheckConstraint("length(adapter_version) > 0", name="ck_knowledge_source_adapter_version"),
        sa.CheckConstraint("poll_interval_seconds >= 300", name="ck_knowledge_source_poll_interval"),
        sa.CheckConstraint("freshness_budget_seconds > 0", name="ck_knowledge_source_freshness_budget"),
        sa.CheckConstraint("length(approval_reason) > 0", name="ck_knowledge_source_approval_reason"),
        sa.ForeignKeyConstraint(
            ["approved_by_account_id"],
            ["accounts.account_id"],
            ondelete="RESTRICT",
            name="fk_knowledge_source_registry_approver",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["knowledge_sources.source_id"],
            ondelete="RESTRICT",
            name="fk_knowledge_source_registry_source",
        ),
        sa.PrimaryKeyConstraint("source_id", "revision", name="pk_knowledge_source_registry_revisions"),
    )
    op.create_index(
        "ix_knowledge_source_registry_enabled",
        "knowledge_source_registry_revisions",
        ["enabled", "source_id", "revision"],
    )
    op.create_table(
        "knowledge_source_allowlist",
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(length=253), nullable=False),
        sa.Column("path_prefix", sa.String(length=1024), nullable=False),
        sa.CheckConstraint("length(host) > 0", name="ck_knowledge_source_allowlist_host"),
        sa.CheckConstraint("length(path_prefix) > 0", name="ck_knowledge_source_allowlist_path"),
        sa.CheckConstraint("path_prefix LIKE '/%'", name="ck_knowledge_source_allowlist_absolute_path"),
        sa.ForeignKeyConstraint(
            ["source_id", "revision"],
            [
                "knowledge_source_registry_revisions.source_id",
                "knowledge_source_registry_revisions.revision",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_source_allowlist_revision",
        ),
        sa.PrimaryKeyConstraint(
            "source_id", "revision", "host", "path_prefix", name="pk_knowledge_source_allowlist"
        ),
    )
    op.create_index(
        "ix_knowledge_source_allowlist_host",
        "knowledge_source_allowlist",
        ["host", "path_prefix"],
    )
    op.create_table(
        "knowledge_source_observations",
        sa.Column("source_observation_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("registry_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("ingest_run_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=256), nullable=True),
        sa.Column("response_class", sa.String(length=64), nullable=False),
        sa.Column("access_mode", sa.String(length=32), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_observation_id LIKE 'source-observation:%'",
            name="ck_knowledge_source_observation_id_prefix",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) = 64",
            name="ck_knowledge_source_observation_idempotency_length",
        ),
        sa.CheckConstraint(
            "length(snapshot_sha256) = 64",
            name="ck_knowledge_source_observation_snapshot_hash_length",
        ),
        sa.CheckConstraint("status_code BETWEEN 200 AND 599", name="ck_knowledge_source_observation_status"),
        sa.CheckConstraint(
            "length(response_class) > 0", name="ck_knowledge_source_observation_response_class"
        ),
        sa.CheckConstraint(
            "length(access_mode) > 0", name="ck_knowledge_source_observation_access_mode"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "registry_revision"],
            [
                "knowledge_source_registry_revisions.source_id",
                "knowledge_source_registry_revisions.revision",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_source_observation_registry_revision",
        ),
        sa.ForeignKeyConstraint(
            ["ingest_run_id"], ["ingest_runs.id"], ondelete="RESTRICT", name="fk_knowledge_source_observation_run"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_sha256"],
            ["source_snapshots.content_sha256"],
            ondelete="RESTRICT",
            name="fk_knowledge_source_observation_snapshot",
        ),
        sa.PrimaryKeyConstraint("source_observation_id", name="pk_knowledge_source_observations"),
        sa.UniqueConstraint(
            "source_id", "idempotency_key", name="uq_knowledge_source_observation_idempotency"
        ),
    )
    op.create_index(
        "ix_knowledge_source_observations_source_time",
        "knowledge_source_observations",
        ["source_id", "observed_at"],
    )
    op.create_index(
        "ix_knowledge_source_observations_snapshot",
        "knowledge_source_observations",
        ["snapshot_sha256"],
    )
    op.create_index(
        "ix_knowledge_source_observations_run",
        "knowledge_source_observations",
        ["ingest_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_source_observations_run", table_name="knowledge_source_observations")
    op.drop_index("ix_knowledge_source_observations_snapshot", table_name="knowledge_source_observations")
    op.drop_index("ix_knowledge_source_observations_source_time", table_name="knowledge_source_observations")
    op.drop_table("knowledge_source_observations")
    op.drop_index("ix_knowledge_source_allowlist_host", table_name="knowledge_source_allowlist")
    op.drop_table("knowledge_source_allowlist")
    op.drop_index("ix_knowledge_source_registry_enabled", table_name="knowledge_source_registry_revisions")
    op.drop_table("knowledge_source_registry_revisions")
    op.drop_table("knowledge_sources")
