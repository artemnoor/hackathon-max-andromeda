from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class KnowledgeSourceModel(Base):
    __tablename__ = "knowledge_sources"

    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(96), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "jurisdiction",
            "issuer_id",
            "identity_key",
            name="uq_knowledge_source_identity",
        ),
        CheckConstraint("source_id LIKE 'source:%'", name="ck_knowledge_source_id_prefix"),
        CheckConstraint("issuer_id LIKE 'issuer:%'", name="ck_knowledge_source_issuer_prefix"),
        CheckConstraint(
            "jurisdiction IN ('federal', 'regional', 'university', 'international', 'unknown')",
            name="ck_knowledge_source_jurisdiction",
        ),
        CheckConstraint("length(identity_key) > 0", name="ck_knowledge_source_identity_key"),
        CheckConstraint("length(display_name) > 0", name="ck_knowledge_source_display_name"),
    )


class KnowledgeSourceRegistryRevisionModel(Base):
    __tablename__ = "knowledge_source_registry_revisions"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sources.source_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    reliability_tier: Mapped[str] = mapped_column(String(40), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(96), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    start_url: Mapped[str] = mapped_column(Text, nullable=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    freshness_budget_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    approved_by_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approval_reason: Mapped[str] = mapped_column(String(512), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_knowledge_source_registry_revision_positive"),
        CheckConstraint(
            "source_kind IN ('normative_document', 'ministry_publication', 'university_admission_rules', "
            "'university_order', 'official_appendix', 'official_news', 'official_feed', 'official_api')",
            name="ck_knowledge_source_kind",
        ),
        CheckConstraint(
            "reliability_tier IN ('primary_normative', 'official_issuer', 'official_university', "
            "'trusted_secondary', 'unverified_secondary', 'community', 'user_supplied', 'unknown')",
            name="ck_knowledge_source_reliability_tier",
        ),
        CheckConstraint("length(adapter_id) > 0", name="ck_knowledge_source_adapter_id"),
        CheckConstraint("length(adapter_version) > 0", name="ck_knowledge_source_adapter_version"),
        CheckConstraint("poll_interval_seconds >= 300", name="ck_knowledge_source_poll_interval"),
        CheckConstraint("freshness_budget_seconds > 0", name="ck_knowledge_source_freshness_budget"),
        CheckConstraint("length(approval_reason) > 0", name="ck_knowledge_source_approval_reason"),
        Index(
            "ix_knowledge_source_registry_enabled",
            "enabled",
            "source_id",
            "revision",
        ),
    )


class KnowledgeSourceAllowlistModel(Base):
    __tablename__ = "knowledge_source_allowlist"

    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(String(253), primary_key=True)
    path_prefix: Mapped[str] = mapped_column(String(1024), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "revision"],
            [
                "knowledge_source_registry_revisions.source_id",
                "knowledge_source_registry_revisions.revision",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_source_allowlist_revision",
        ),
        CheckConstraint("length(host) > 0", name="ck_knowledge_source_allowlist_host"),
        CheckConstraint("length(path_prefix) > 0", name="ck_knowledge_source_allowlist_path"),
        CheckConstraint("path_prefix LIKE '/%'", name="ck_knowledge_source_allowlist_absolute_path"),
        Index("ix_knowledge_source_allowlist_host", "host", "path_prefix"),
    )


class KnowledgeSourceObservationModel(Base):
    __tablename__ = "knowledge_source_observations"

    source_observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    registry_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    ingest_run_id: Mapped[str] = mapped_column(
        ForeignKey("ingest_runs.id", ondelete="RESTRICT"), nullable=False
    )
    snapshot_sha256: Mapped[str] = mapped_column(
        ForeignKey("source_snapshots.content_sha256", ondelete="RESTRICT"), nullable=False
    )
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    response_class: Mapped[str] = mapped_column(String(64), nullable=False)
    access_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "registry_revision"],
            [
                "knowledge_source_registry_revisions.source_id",
                "knowledge_source_registry_revisions.revision",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_source_observation_registry_revision",
        ),
        UniqueConstraint(
            "source_id",
            "idempotency_key",
            name="uq_knowledge_source_observation_idempotency",
        ),
        CheckConstraint(
            "source_observation_id LIKE 'source-observation:%'",
            name="ck_knowledge_source_observation_id_prefix",
        ),
        CheckConstraint("length(idempotency_key) = 64", name="ck_knowledge_source_observation_idempotency_length"),
        CheckConstraint("length(snapshot_sha256) = 64", name="ck_knowledge_source_observation_snapshot_hash_length"),
        CheckConstraint("status_code BETWEEN 200 AND 599", name="ck_knowledge_source_observation_status"),
        CheckConstraint("length(response_class) > 0", name="ck_knowledge_source_observation_response_class"),
        CheckConstraint("length(access_mode) > 0", name="ck_knowledge_source_observation_access_mode"),
        Index(
            "ix_knowledge_source_observations_source_time",
            "source_id",
            "observed_at",
        ),
        Index("ix_knowledge_source_observations_snapshot", "snapshot_sha256"),
        Index("ix_knowledge_source_observations_run", "ingest_run_id"),
    )


class KnowledgeSourcePollAttemptModel(Base):
    __tablename__ = "knowledge_source_poll_attempts"

    attempt_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    registry_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_snapshot_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_successful_snapshot_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_observation_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_source_observations.source_observation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "registry_revision"],
            [
                "knowledge_source_registry_revisions.source_id",
                "knowledge_source_registry_revisions.revision",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_source_poll_attempt_registry_revision",
        ),
        CheckConstraint("attempt_id LIKE 'poll-attempt:%'", name="ck_knowledge_poll_attempt_id_prefix"),
        CheckConstraint("outcome IN ('new', 'changed', 'unchanged', 'unavailable', 'removed')", name="ck_knowledge_poll_outcome"),
        CheckConstraint("length(parser_version) > 0", name="ck_knowledge_poll_parser_version"),
        CheckConstraint("retry_count BETWEEN 0 AND 10", name="ck_knowledge_poll_retry_count"),
        CheckConstraint("extracted_candidate_count BETWEEN 0 AND 500", name="ck_knowledge_poll_candidate_count"),
        CheckConstraint(
            "(previous_snapshot_sha256 IS NULL OR length(previous_snapshot_sha256) = 64) AND "
            "(snapshot_sha256 IS NULL OR length(snapshot_sha256) = 64) AND "
            "(last_successful_snapshot_sha256 IS NULL OR length(last_successful_snapshot_sha256) = 64)",
            name="ck_knowledge_poll_snapshot_hash_lengths",
        ),
        CheckConstraint("completed_at >= started_at", name="ck_knowledge_poll_time_order"),
        CheckConstraint(
            "next_retry_at IS NULL OR next_retry_at > completed_at",
            name="ck_knowledge_poll_retry_after_completion",
        ),
        CheckConstraint(
            "(outcome IN ('new', 'changed', 'unchanged') AND source_observation_id IS NOT NULL "
            "AND snapshot_sha256 IS NOT NULL AND failure_code IS NULL AND next_retry_at IS NULL AND retry_count = 0) OR "
            "(outcome IN ('unavailable', 'removed') AND source_observation_id IS NULL "
            "AND snapshot_sha256 IS NULL AND failure_code IS NOT NULL AND next_retry_at IS NOT NULL "
            "AND extracted_candidate_count = 0)",
            name="ck_knowledge_poll_success_failure_shape",
        ),
        Index("ix_knowledge_poll_attempt_source_time", "source_id", "completed_at"),
        Index("ix_knowledge_poll_attempt_next_retry", "next_retry_at"),
    )


__all__ = [
    "KnowledgeSourceAllowlistModel",
    "KnowledgeSourceModel",
    "KnowledgeSourceObservationModel",
    "KnowledgeSourcePollAttemptModel",
    "KnowledgeSourceRegistryRevisionModel",
]
