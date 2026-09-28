from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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


class KnowledgeClaimRelationModel(Base):
    __tablename__ = "knowledge_claim_relations"

    relation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    relation_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_claim_id: Mapped[str] = mapped_column(String(70), nullable=False)
    source_claim_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    target_claim_id: Mapped[str] = mapped_column(String(70), nullable=False)
    target_claim_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_claim_id", "source_claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_relation_source_claim",
        ),
        ForeignKeyConstraint(
            ["target_claim_id", "target_claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_relation_target_claim",
        ),
        CheckConstraint("relation_id LIKE 'knowledge-relation:%'", name="ck_knowledge_relation_id_prefix"),
        CheckConstraint("revision >= 1", name="ck_knowledge_relation_revision_positive"),
        CheckConstraint("length(content_hash) = 64", name="ck_knowledge_relation_content_hash"),
        CheckConstraint(
            "relation_kind IN ('supported_by', 'contradicts', 'clarifies', 'derived_from')",
            name="ck_knowledge_relation_kind",
        ),
        CheckConstraint(
            "source_claim_id != target_claim_id OR source_claim_revision != target_claim_revision",
            name="ck_knowledge_relation_not_self",
        ),
        CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR valid_start IS NULL OR "
            "valid_end IS NULL OR valid_start < valid_end",
            name="ck_knowledge_relation_valid_period",
        ),
        CheckConstraint(
            "review_state IN ('candidate', 'approved', 'rejected', 'unresolved')",
            name="ck_knowledge_relation_review_state",
        ),
        UniqueConstraint(
            "relation_id", "revision", "content_hash", name="uq_knowledge_relation_revision_hash"
        ),
        Index("ix_knowledge_relation_source", "source_claim_id", "source_claim_revision", "relation_kind"),
        Index("ix_knowledge_relation_target", "target_claim_id", "target_claim_revision", "relation_kind"),
        Index("ix_knowledge_relation_review", "review_state", "recorded_at"),
    )


class KnowledgeClaimRelationEvidenceModel(Base):
    __tablename__ = "knowledge_claim_relation_evidence"

    relation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    relation_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_observation_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_source_observations.source_observation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot_sha256: Mapped[str] = mapped_column(
        ForeignKey("source_snapshots.content_sha256", ondelete="RESTRICT"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    locator_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_table: Mapped[str | None] = mapped_column(String(256), nullable=True)
    locator_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_section: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locator_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locator_record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["relation_id", "relation_revision"],
            ["knowledge_claim_relations.relation_id", "knowledge_claim_relations.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_relation_evidence_revision",
        ),
        CheckConstraint("ordinal >= 0", name="ck_knowledge_relation_evidence_ordinal"),
        CheckConstraint("length(source_url) > 0", name="ck_knowledge_relation_evidence_url"),
        CheckConstraint("locator_page IS NULL OR locator_page >= 1", name="ck_knowledge_relation_evidence_page"),
        CheckConstraint("locator_row IS NULL OR locator_row >= 1", name="ck_knowledge_relation_evidence_row"),
        Index("ix_knowledge_relation_evidence_observation", "source_observation_id"),
    )


__all__ = ["KnowledgeClaimRelationEvidenceModel", "KnowledgeClaimRelationModel"]
