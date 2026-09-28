"""Immutable conflict-group revisions, evidence links and decision history."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class KnowledgeConflictGroupModel(Base):
    __tablename__ = "knowledge_conflict_groups"

    conflict_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    conflict_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    scope_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scope_id: Mapped[str | None] = mapped_column(String(320), nullable=True)
    valid_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("conflict_id LIKE 'knowledge-conflict:%'", name="ck_knowledge_conflict_id_prefix"),
        CheckConstraint("revision >= 1", name="ck_knowledge_conflict_revision_positive"),
        CheckConstraint("length(content_hash) = 64", name="ck_knowledge_conflict_content_hash"),
        CheckConstraint(
            "conflict_kind IN ('contradictory_claims', 'policy_precedence', 'stale_source_disagreement', "
            "'same_issuer_amendment', 'overlapping_scope_time')",
            name="ck_knowledge_conflict_kind",
        ),
        CheckConstraint(
            "(scope_level IS NULL AND scope_id IS NULL) OR "
            "(scope_level = 'federal' AND scope_id IS NULL) OR "
            "(scope_level = 'unknown' AND scope_id IS NULL) OR "
            "(scope_level NOT IN ('federal', 'unknown') AND scope_id IS NOT NULL AND length(scope_id) > 0)",
            name="ck_knowledge_conflict_scope",
        ),
        CheckConstraint(
            "scope_level IS NULL OR scope_level IN ('federal', 'ministry', 'university', 'campus', 'faculty', "
            "'department', 'education_level', 'direction', 'program', 'admission_route', 'competition_type', "
            "'applicant_category', 'olympiad', 'olympiad_profile', 'subject', 'unknown')",
            name="ck_knowledge_conflict_scope_level",
        ),
        CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR "
            "valid_start IS NULL OR valid_end IS NULL OR valid_start < valid_end",
            name="ck_knowledge_conflict_valid_period",
        ),
        UniqueConstraint(
            "conflict_id", "revision", "content_hash", name="uq_knowledge_conflict_revision_hash"
        ),
        Index("ix_knowledge_conflict_latest", "conflict_id", "revision"),
        Index(
            "ix_knowledge_conflict_scope_time",
            "conflict_kind",
            "scope_level",
            "scope_id",
            "valid_start",
            "valid_end",
        ),
    )


class KnowledgeConflictParticipantModel(Base):
    __tablename__ = "knowledge_conflict_participants"

    conflict_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    group_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    participant_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    claim_id: Mapped[str | None] = mapped_column(String(70), nullable=True)
    claim_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_event_id: Mapped[str | None] = mapped_column(String(78), nullable=True)
    change_event_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_rule_id: Mapped[str | None] = mapped_column(String(140), nullable=True)
    policy_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["conflict_id", "group_revision"],
            ["knowledge_conflict_groups.conflict_id", "knowledge_conflict_groups.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_conflict_participant_group",
        ),
        ForeignKeyConstraint(
            ["claim_id", "claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_conflict_claim_participant",
        ),
        ForeignKeyConstraint(
            ["change_event_id", "change_event_revision"],
            ["knowledge_change_events.change_event_id", "knowledge_change_events.revision"],
            ondelete="RESTRICT",
            name="fk_knowledge_conflict_event_participant",
        ),
        ForeignKeyConstraint(
            ["policy_rule_id", "policy_revision", "policy_hash"],
            ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision", "policy_rule_revisions.content_hash"],
            ondelete="RESTRICT",
            name="fk_knowledge_conflict_policy_participant",
        ),
        CheckConstraint("ordinal >= 0", name="ck_knowledge_conflict_participant_ordinal"),
        CheckConstraint(
            "role IN ('competing', 'prior', 'successor')", name="ck_knowledge_conflict_participant_role"
        ),
        CheckConstraint(
            "(participant_kind = 'claim_revision' AND claim_id IS NOT NULL AND claim_revision IS NOT NULL "
            "AND claim_hash IS NOT NULL AND change_event_id IS NULL AND change_event_revision IS NULL "
            "AND policy_rule_id IS NULL AND policy_revision IS NULL AND policy_hash IS NULL) OR "
            "(participant_kind = 'change_event_revision' AND claim_id IS NULL AND claim_revision IS NULL "
            "AND claim_hash IS NULL AND change_event_id IS NOT NULL AND change_event_revision IS NOT NULL "
            "AND policy_rule_id IS NULL AND policy_revision IS NULL AND policy_hash IS NULL) OR "
            "(participant_kind = 'policy_rule_revision' AND claim_id IS NULL AND claim_revision IS NULL "
            "AND claim_hash IS NULL AND change_event_id IS NULL AND change_event_revision IS NULL "
            "AND policy_rule_id IS NOT NULL AND policy_revision IS NOT NULL AND policy_hash IS NOT NULL)",
            name="ck_knowledge_conflict_participant_reference_shape",
        ),
        CheckConstraint("claim_revision IS NULL OR claim_revision >= 1", name="ck_knowledge_conflict_claim_revision"),
        CheckConstraint("change_event_revision IS NULL OR change_event_revision >= 1", name="ck_knowledge_conflict_event_revision"),
        CheckConstraint("policy_revision IS NULL OR policy_revision >= 1", name="ck_knowledge_conflict_policy_revision"),
        CheckConstraint("claim_hash IS NULL OR length(claim_hash) = 64", name="ck_knowledge_conflict_claim_hash"),
        CheckConstraint("policy_hash IS NULL OR length(policy_hash) = 64", name="ck_knowledge_conflict_policy_hash"),
        Index(
            "uq_knowledge_conflict_participant_claim_ref",
            "conflict_id",
            "group_revision",
            "claim_id",
            "claim_revision",
            "claim_hash",
            unique=True,
            sqlite_where=text("participant_kind = 'claim_revision'"),
            postgresql_where=text("participant_kind = 'claim_revision'"),
        ),
        Index(
            "uq_knowledge_conflict_participant_change_event_ref",
            "conflict_id",
            "group_revision",
            "change_event_id",
            "change_event_revision",
            unique=True,
            sqlite_where=text("participant_kind = 'change_event_revision'"),
            postgresql_where=text("participant_kind = 'change_event_revision'"),
        ),
        Index(
            "uq_knowledge_conflict_participant_policy_ref",
            "conflict_id",
            "group_revision",
            "policy_rule_id",
            "policy_revision",
            "policy_hash",
            unique=True,
            sqlite_where=text("participant_kind = 'policy_rule_revision'"),
            postgresql_where=text("participant_kind = 'policy_rule_revision'"),
        ),
        Index("ix_knowledge_conflict_participant_claim", "claim_id", "claim_revision"),
        Index("ix_knowledge_conflict_participant_policy", "policy_rule_id", "policy_revision"),
    )


class KnowledgeConflictEvidenceModel(Base):
    __tablename__ = "knowledge_conflict_evidence"

    conflict_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    group_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    participant_ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
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
            ["conflict_id", "group_revision", "participant_ordinal"],
            [
                "knowledge_conflict_participants.conflict_id",
                "knowledge_conflict_participants.group_revision",
                "knowledge_conflict_participants.ordinal",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_conflict_evidence_participant",
        ),
        CheckConstraint("ordinal >= 0", name="ck_knowledge_conflict_evidence_ordinal"),
        CheckConstraint("length(source_url) > 0", name="ck_knowledge_conflict_evidence_url"),
        CheckConstraint("length(snapshot_sha256) = 64", name="ck_knowledge_conflict_evidence_snapshot_hash"),
        CheckConstraint("locator_page IS NULL OR locator_page >= 1", name="ck_knowledge_conflict_evidence_page"),
        CheckConstraint("locator_row IS NULL OR locator_row >= 1", name="ck_knowledge_conflict_evidence_row"),
        Index("ix_knowledge_conflict_evidence_observation", "source_observation_id"),
    )


class KnowledgeConflictEventModel(Base):
    __tablename__ = "knowledge_conflict_events"

    event_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    conflict_id: Mapped[str] = mapped_column(String(96), nullable=False)
    group_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    group_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    resolution_participant_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["conflict_id", "group_revision", "group_hash"],
            ["knowledge_conflict_groups.conflict_id", "knowledge_conflict_groups.revision", "knowledge_conflict_groups.content_hash"],
            ondelete="RESTRICT",
            name="fk_knowledge_conflict_event_group_hash",
        ),
        ForeignKeyConstraint(
            ["conflict_id", "group_revision", "resolution_participant_ordinal"],
            [
                "knowledge_conflict_participants.conflict_id",
                "knowledge_conflict_participants.group_revision",
                "knowledge_conflict_participants.ordinal",
            ],
            ondelete="RESTRICT",
            name="fk_knowledge_conflict_event_resolution_participant",
        ),
        CheckConstraint("event_id LIKE 'knowledge-conflict-event:%'", name="ck_knowledge_conflict_event_id_prefix"),
        CheckConstraint("sequence >= 1", name="ck_knowledge_conflict_event_sequence"),
        CheckConstraint("length(group_hash) = 64", name="ck_knowledge_conflict_event_group_hash"),
        CheckConstraint("length(reason) > 0", name="ck_knowledge_conflict_event_reason"),
        CheckConstraint(
            "(event_kind = 'opened' AND sequence = 1 AND actor_account_id IS NULL AND resolution_participant_ordinal IS NULL) OR "
            "(event_kind = 'resolved_by_supersession' AND sequence > 1 AND actor_account_id IS NULL AND resolution_participant_ordinal IS NOT NULL) OR "
            "(event_kind = 'resolved_by_human_review' AND sequence > 1 AND actor_account_id IS NOT NULL AND resolution_participant_ordinal IS NOT NULL) OR "
            "(event_kind IN ('dismissed', 'reopened') AND sequence > 1 AND actor_account_id IS NOT NULL AND resolution_participant_ordinal IS NULL)",
            name="ck_knowledge_conflict_event_shape",
        ),
        UniqueConstraint("conflict_id", "group_revision", "sequence", name="uq_knowledge_conflict_event_sequence"),
        Index("ix_knowledge_conflict_events_actor_time", "actor_account_id", "recorded_at"),
    )


__all__ = [
    "KnowledgeConflictEventModel",
    "KnowledgeConflictEvidenceModel",
    "KnowledgeConflictGroupModel",
    "KnowledgeConflictParticipantModel",
]
