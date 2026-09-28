from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class SemanticFeatureModel(Base):
    __tablename__ = "semantic_features"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    feature_group: Mapped[str] = mapped_column(String(32), nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(64), nullable=False, default="semantic-taxonomy.v1", server_default="semantic-taxonomy.v1")
    active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("id LIKE 'semantic-feature:%'", name="ck_semantic_feature_id"),
        CheckConstraint("length(code) > 0", name="ck_semantic_feature_code"),
        Index("ix_semantic_features_code_version", "code", "semantic_version"),
        Index("ix_semantic_features_definition_active", "definition_version", "active", "code"),
    )


class DisciplineSemanticFeatureModel(Base):
    __tablename__ = "discipline_semantic_features"

    # Keep this length aligned with the historical 0026 migration. Discipline
    # identities are currently bounded to 64 characters by the canonical model.
    discipline_id: Mapped[str] = mapped_column(
        String(256),
        ForeignKey("disciplines.id", ondelete="CASCADE"),
        primary_key=True,
    )
    feature_id: Mapped[str] = mapped_column(ForeignKey("semantic_features.id"), primary_key=True)
    semantic_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    classifier_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="available")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    classification_method: Mapped[str] = mapped_column(String(16), nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unreviewed")
    source_hash: Mapped[str | None] = mapped_column(ForeignKey("source_snapshots.content_sha256"), nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_runs.id"), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("value IS NULL OR (value >= 0 AND value <= 1)", name="ck_discipline_semantic_value"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_discipline_semantic_confidence"),
        CheckConstraint("status IN ('available', 'unknown', 'unavailable')", name="ck_discipline_semantic_status"),
        CheckConstraint("review_status IN ('unreviewed', 'reviewed', 'rejected', 'needs_review')", name="ck_discipline_semantic_review_status"),
        CheckConstraint("(status = 'available' AND value IS NOT NULL) OR (status <> 'available' AND value IS NULL)", name="ck_discipline_semantic_status_value"),
        Index("ix_discipline_semantic_feature_lookup", "feature_id", "semantic_version", "discipline_id"),
    )


class CurriculumItemSemanticFeatureModel(Base):
    __tablename__ = "curriculum_item_semantic_features"

    curriculum_item_id: Mapped[str] = mapped_column(ForeignKey("curriculum_items.id", ondelete="CASCADE"), primary_key=True)
    feature_id: Mapped[str] = mapped_column(ForeignKey("semantic_features.id"), primary_key=True)
    semantic_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    classifier_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="available")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    classification_method: Mapped[str] = mapped_column(String(16), nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unreviewed")
    source_hash: Mapped[str | None] = mapped_column(ForeignKey("source_snapshots.content_sha256"), nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(ForeignKey("ingest_runs.id"), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    overrides_discipline_default: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("value IS NULL OR (value >= 0 AND value <= 1)", name="ck_curriculum_item_semantic_value"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_curriculum_item_semantic_confidence"),
        CheckConstraint("status IN ('available', 'unknown', 'unavailable')", name="ck_curriculum_item_semantic_status"),
        CheckConstraint("review_status IN ('unreviewed', 'reviewed', 'rejected', 'needs_review')", name="ck_curriculum_item_semantic_review_status"),
        CheckConstraint("(status = 'available' AND value IS NOT NULL) OR (status <> 'available' AND value IS NULL)", name="ck_curriculum_item_semantic_status_value"),
        Index("ix_curriculum_item_semantic_feature_lookup", "feature_id", "semantic_version", "curriculum_item_id"),
    )


class SemanticEnrichmentRunModel(Base):
    __tablename__ = "semantic_enrichment_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    ingest_run_id: Mapped[str] = mapped_column(ForeignKey("ingest_runs.id"), nullable=False)
    university_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(64), nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(64), nullable=False)
    affected_item_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    changed_item_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    affected_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    classified_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unchanged_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_of_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_semantic_enrichment_run_status"),
        CheckConstraint("affected_item_count >= 0", name="ck_semantic_enrichment_run_affected_count"),
        CheckConstraint("classified_item_count >= 0", name="ck_semantic_enrichment_run_classified_count"),
        CheckConstraint("unchanged_item_count >= 0", name="ck_semantic_enrichment_run_unchanged_count"),
        CheckConstraint("failed_item_count >= 0", name="ck_semantic_enrichment_run_failed_count"),
        Index("ix_semantic_enrichment_runs_ingest_run", "ingest_run_id"),
        Index("ix_semantic_enrichment_runs_status_started", "status", "started_at"),
    )
