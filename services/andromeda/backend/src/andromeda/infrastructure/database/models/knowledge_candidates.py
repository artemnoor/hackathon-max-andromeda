from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base

_CLAIM_VALUE_CLEAR = (
    "proposition_value_text IS NULL AND proposition_value_decimal IS NULL AND "
    "proposition_value_boolean IS NULL AND proposition_value_date IS NULL AND "
    "proposition_value_datetime IS NULL AND proposition_value_identifier IS NULL"
)


class KnowledgeClaimModel(Base):
    __tablename__ = "knowledge_claims"

    claim_id: Mapped[str] = mapped_column(String(70), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_observation_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_source_observations.source_observation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    text_start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    text_end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    assertion_text: Mapped[str] = mapped_column(Text, nullable=False)
    assertion_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    proposition_predicate: Mapped[str | None] = mapped_column(String(96), nullable=True)
    proposition_subject_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    proposition_subject_id: Mapped[str | None] = mapped_column(String(320), nullable=True)
    proposition_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposition_value_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    proposition_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposition_value_decimal: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), nullable=True)
    proposition_value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    proposition_value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    proposition_value_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proposition_value_identifier: Mapped[str | None] = mapped_column(String(320), nullable=True)
    claimed_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    review_state: Mapped[str] = mapped_column(String(40), nullable=False)
    valid_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    extractor_id: Mapped[str] = mapped_column(String(96), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("claim_id LIKE 'claim:%'", name="ck_knowledge_claim_id_prefix"),
        CheckConstraint("revision >= 1", name="ck_knowledge_claim_revision"),
        CheckConstraint("text_start_offset >= 0 AND text_start_offset < text_end_offset", name="ck_knowledge_claim_text_offsets"),
        CheckConstraint("length(assertion_text) > 0", name="ck_knowledge_claim_text"),
        CheckConstraint("length(assertion_text_sha256) = 64", name="ck_knowledge_claim_text_hash"),
        CheckConstraint(
            f"(proposition_predicate IS NULL AND proposition_subject_kind IS NULL AND "
            f"proposition_subject_id IS NULL AND proposition_unit IS NULL AND "
            f"proposition_value_kind IS NULL AND {_CLAIM_VALUE_CLEAR}) OR "
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
        CheckConstraint(
            "claimed_stage IN ('rumor', 'hypothesis', 'announced', 'proposal', 'draft', 'under_review', "
            "'adopted', 'published', 'future_effective', 'effective', 'superseded', 'repealed', "
            "'withdrawn', 'rejected', 'unknown')",
            name="ck_knowledge_claim_claimed_stage",
        ),
        CheckConstraint(
            "review_state IN ('unreviewed', 'needs_review', 'accepted_as_source_assertion', 'rejected', 'unresolved', 'duplicate')",
            name="ck_knowledge_claim_review_state",
        ),
        CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR "
            "valid_start IS NOT NULL AND (valid_end IS NULL OR valid_start < valid_end)",
            name="ck_knowledge_claim_valid_period",
        ),
        CheckConstraint(
            "effective_start IS NULL AND effective_end IS NULL OR "
            "effective_start IS NOT NULL AND (effective_end IS NULL OR effective_start < effective_end)",
            name="ck_knowledge_claim_effective_period",
        ),
        CheckConstraint(
            "claimed_stage NOT IN ('future_effective', 'effective', 'superseded', 'repealed') "
            "OR effective_start IS NOT NULL",
            name="ck_knowledge_claim_stage_requires_effective_date",
        ),
        CheckConstraint(
            "claimed_stage != 'future_effective' OR effective_start > recorded_at",
            name="ck_knowledge_claim_future_stage_after_recording",
        ),
        CheckConstraint(
            "claimed_stage NOT IN ('effective', 'superseded', 'repealed') "
            "OR effective_start <= recorded_at",
            name="ck_knowledge_claim_active_stage_after_effective_time",
        ),
        CheckConstraint(
            "extraction_method IN ('structured_document', 'deterministic_parser', 'manual', 'jev_suggestion')",
            name="ck_knowledge_claim_extraction_method",
        ),
        CheckConstraint("length(extractor_id) > 0", name="ck_knowledge_claim_extractor_id"),
        CheckConstraint("length(extractor_version) > 0", name="ck_knowledge_claim_extractor_version"),
        CheckConstraint(
            "extraction_confidence IS NULL OR extraction_confidence BETWEEN 0 AND 1",
            name="ck_knowledge_claim_extraction_confidence",
        ),
        CheckConstraint(
            "extraction_method != 'jev_suggestion' OR extraction_confidence IS NOT NULL",
            name="ck_knowledge_claim_jev_confidence",
        ),
        Index("ix_knowledge_claims_observation", "source_observation_id", "text_start_offset"),
        Index("ix_knowledge_claims_stage_review", "claimed_stage", "review_state", "recorded_at"),
        Index("ix_knowledge_claims_recorded_at", "recorded_at"),
        Index(
            "ix_knowledge_claims_predicate_subject_time",
            "proposition_predicate",
            "proposition_subject_id",
            "recorded_at",
        ),
    )


class KnowledgeClaimEvidenceModel(Base):
    __tablename__ = "knowledge_claim_evidence"

    claim_id: Mapped[str] = mapped_column(String(70), primary_key=True)
    claim_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    relationship: Mapped[str] = mapped_column(String(24), nullable=False)
    source_observation_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_source_observations.source_observation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    locator_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_table: Mapped[str | None] = mapped_column(String(256), nullable=True)
    locator_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_section: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locator_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locator_record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["claim_id", "claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_claim_evidence_claim",
        ),
        CheckConstraint("ordinal >= 0", name="ck_knowledge_claim_evidence_ordinal"),
        CheckConstraint(
            "relationship IN ('originates_from', 'supports', 'contradicts', 'qualifies')",
            name="ck_knowledge_claim_evidence_relationship",
        ),
        CheckConstraint("length(source_url) > 0", name="ck_knowledge_claim_evidence_url"),
        CheckConstraint("locator_page IS NULL OR locator_page >= 1", name="ck_knowledge_claim_evidence_page"),
        CheckConstraint("locator_row IS NULL OR locator_row >= 1", name="ck_knowledge_claim_evidence_row"),
        Index("ix_knowledge_claim_evidence_observation", "source_observation_id"),
    )


class KnowledgeChangeEventModel(Base):
    __tablename__ = "knowledge_change_events"

    change_event_id: Mapped[str] = mapped_column(String(78), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    primary_source_observation_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_source_observations.source_observation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    review_state: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("change_event_id LIKE 'change-event:%'", name="ck_knowledge_change_event_id_prefix"),
        CheckConstraint("revision >= 1", name="ck_knowledge_change_event_revision"),
        CheckConstraint(
            "event_kind IN ('hypothesis_reported', 'announcement_published', 'proposal_published', "
            "'draft_published', 'decision_adopted', 'document_published', 'rule_effective', "
            "'rule_amended', 'rule_superseded', 'rule_repealed', 'proposal_withdrawn', "
            "'proposal_rejected', 'unknown')",
            name="ck_knowledge_change_event_kind",
        ),
        CheckConstraint(
            "review_state IN ('needs_review', 'accepted_as_source_event', 'rejected', 'unresolved', 'duplicate')",
            name="ck_knowledge_change_event_review_state",
        ),
        CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR "
            "valid_start IS NOT NULL AND (valid_end IS NULL OR valid_start < valid_end)",
            name="ck_knowledge_change_event_valid_period",
        ),
        CheckConstraint(
            "effective_start IS NULL AND effective_end IS NULL OR "
            "effective_start IS NOT NULL AND (effective_end IS NULL OR effective_start < effective_end)",
            name="ck_knowledge_change_event_effective_period",
        ),
        CheckConstraint(
            "event_kind != 'announcement_published' OR announced_at IS NOT NULL",
            name="ck_knowledge_change_event_announcement_time",
        ),
        CheckConstraint(
            "event_kind NOT IN ('proposal_published', 'draft_published', 'document_published') OR published_at IS NOT NULL",
            name="ck_knowledge_change_event_publication_time",
        ),
        CheckConstraint(
            "event_kind != 'decision_adopted' OR adopted_at IS NOT NULL",
            name="ck_knowledge_change_event_adoption_time",
        ),
        CheckConstraint(
            "event_kind != 'rule_effective' OR effective_start IS NOT NULL",
            name="ck_knowledge_change_event_effective_time",
        ),
        Index("ix_knowledge_change_events_review", "review_state", "recorded_at"),
    )


class KnowledgeChangeEventClaimModel(Base):
    __tablename__ = "knowledge_change_event_claims"

    change_event_id: Mapped[str] = mapped_column(String(78), primary_key=True)
    event_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(70), nullable=False)
    claim_revision: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["change_event_id", "event_revision"],
            ["knowledge_change_events.change_event_id", "knowledge_change_events.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_change_event_claim_event",
        ),
        ForeignKeyConstraint(
            ["claim_id", "claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_change_event_claim_revision",
        ),
        CheckConstraint("ordinal >= 0", name="ck_knowledge_change_event_claim_ordinal"),
        UniqueConstraint(
            "change_event_id", "event_revision", "claim_id", "claim_revision",
            name="uq_knowledge_change_event_claim_ref",
        ),
        Index("ix_knowledge_change_event_claim_claim", "claim_id", "claim_revision"),
    )


class KnowledgeChangeEventEvidenceModel(Base):
    __tablename__ = "knowledge_change_event_evidence"

    change_event_id: Mapped[str] = mapped_column(String(78), primary_key=True)
    event_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_observation_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_source_observations.source_observation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    locator_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_table: Mapped[str | None] = mapped_column(String(256), nullable=True)
    locator_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator_section: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locator_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locator_record_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inferred: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["change_event_id", "event_revision"],
            ["knowledge_change_events.change_event_id", "knowledge_change_events.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_change_event_evidence_event",
        ),
        CheckConstraint("ordinal >= 0", name="ck_knowledge_change_event_evidence_ordinal"),
        CheckConstraint("length(source_url) > 0", name="ck_knowledge_change_event_evidence_url"),
        CheckConstraint("locator_page IS NULL OR locator_page >= 1", name="ck_knowledge_change_event_evidence_page"),
        CheckConstraint("locator_row IS NULL OR locator_row >= 1", name="ck_knowledge_change_event_evidence_row"),
        Index("ix_knowledge_change_event_evidence_observation", "source_observation_id"),
    )


class KnowledgeClaimCandidateClusterModel(Base):
    __tablename__ = "knowledge_claim_candidate_clusters"

    cluster_id: Mapped[str] = mapped_column(String(78), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(83), nullable=False, unique=True)
    fingerprint_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("cluster_id LIKE 'claim-cluster:%'", name="ck_knowledge_claim_cluster_id_prefix"),
        CheckConstraint("fingerprint LIKE 'claim-fingerprint:%'", name="ck_knowledge_claim_cluster_fingerprint_prefix"),
        CheckConstraint("length(fingerprint_version) > 0", name="ck_knowledge_claim_cluster_version"),
        Index("ix_knowledge_claim_clusters_created", "created_at"),
    )


class KnowledgeClaimCandidateClusterMemberModel(Base):
    __tablename__ = "knowledge_claim_candidate_cluster_members"

    cluster_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_claim_candidate_clusters.cluster_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    claim_id: Mapped[str] = mapped_column(String(70), primary_key=True)
    claim_revision: Mapped[int] = mapped_column(Integer, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["claim_id", "claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_claim_cluster_member_claim",
        ),
        CheckConstraint("claim_revision >= 1", name="ck_knowledge_claim_cluster_member_revision"),
        Index("ix_knowledge_claim_cluster_members_claim", "claim_id", "claim_revision"),
    )


__all__ = [
    "KnowledgeChangeEventClaimModel",
    "KnowledgeChangeEventEvidenceModel",
    "KnowledgeChangeEventModel",
    "KnowledgeClaimCandidateClusterMemberModel",
    "KnowledgeClaimCandidateClusterModel",
    "KnowledgeClaimEvidenceModel",
    "KnowledgeClaimModel",
]
