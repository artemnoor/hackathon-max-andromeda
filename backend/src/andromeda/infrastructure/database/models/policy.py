"""Persistence models for immutable policy selectors and approval history."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    JSON,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class PolicyRuleRevisionModel(Base):
    __tablename__ = "policy_rule_revisions"

    rule_id: Mapped[str] = mapped_column(String(140), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    family_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    authority_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    selector_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(cast(Any, JSONB)(), "postgresql"), nullable=False
    )
    scope_level: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(320), nullable=True)
    owner_module: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_rule_id: Mapped[str] = mapped_column(String(320), nullable=False)
    owner_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_revision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
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
        CheckConstraint("rule_id LIKE 'policy-rule:%'", name="ck_policy_rule_id_prefix"),
        CheckConstraint("revision >= 1", name="ck_policy_rule_revision_positive"),
        CheckConstraint("length(content_hash) = 64", name="ck_policy_rule_content_hash_length"),
        CheckConstraint(
            "(schema_version = 'policy-rule.v1' AND family_id IS NULL AND authority_level IS NULL "
            "AND owner_revision_hash IS NULL) OR "
            "(schema_version = 'policy-rule.v2' AND family_id LIKE 'policy-family:%' AND "
            "authority_level IN ('federal_normative', 'regulator_normative', 'university_normative', 'unresolved') "
            "AND owner_revision_hash IS NULL) OR "
            "(schema_version = 'policy-rule.v3' AND family_id LIKE 'policy-family:%' AND "
            "authority_level IN ('federal_normative', 'regulator_normative', 'university_normative', 'unresolved') "
            "AND owner_revision_hash IS NOT NULL AND length(owner_revision_hash) = 64)",
            name="ck_policy_rule_schema_authority",
        ),
        CheckConstraint(
            "scope_level IN ('federal', 'ministry', 'university', 'campus', 'faculty', 'department', "
            "'education_level', 'direction', 'program', 'admission_route', 'competition_type', "
            "'applicant_category', 'olympiad', 'olympiad_profile', 'subject')",
            name="ck_policy_rule_scope_level",
        ),
        CheckConstraint(
            "(scope_level = 'federal' AND scope_id IS NULL) OR "
            "(scope_level != 'federal' AND scope_id IS NOT NULL AND length(scope_id) > 0)",
            name="ck_policy_rule_scope_reference",
        ),
        CheckConstraint(
            "owner_module IN ('admission_benefits', 'admissions', 'admission_fit')",
            name="ck_policy_rule_owner_module",
        ),
        CheckConstraint("owner_revision >= 1", name="ck_policy_rule_owner_revision"),
        CheckConstraint(
            "owner_revision_hash IS NULL OR length(owner_revision_hash) = 64",
            name="ck_policy_rule_owner_revision_hash",
        ),
        CheckConstraint(
            "lifecycle IN ('rumor', 'hypothesis', 'announced', 'proposal', 'draft', 'under_review', "
            "'adopted', 'published', 'future_effective', 'effective', 'superseded', 'repealed', "
            "'withdrawn', 'rejected', 'unknown')",
            name="ck_policy_rule_lifecycle",
        ),
        CheckConstraint(
            "valid_start IS NULL AND valid_end IS NULL OR "
            "valid_start IS NOT NULL AND (valid_end IS NULL OR valid_start < valid_end)",
            name="ck_policy_rule_valid_period",
        ),
        CheckConstraint(
            "effective_start IS NULL AND effective_end IS NULL OR "
            "effective_start IS NOT NULL AND (effective_end IS NULL OR effective_start < effective_end)",
            name="ck_policy_rule_effective_period",
        ),
        CheckConstraint("recorded_at >= captured_at", name="ck_policy_rule_recorded_after_capture"),
        UniqueConstraint("rule_id", "content_hash", name="uq_policy_rule_content_hash"),
        UniqueConstraint("rule_id", "revision", "content_hash", name="uq_policy_rule_revision_hash"),
        Index("ix_policy_rule_scope_lifecycle", "scope_level", "scope_id", "lifecycle"),
        Index("ix_policy_rule_recorded_at", "rule_id", "recorded_at"),
        Index("ix_policy_rule_effective_period", "effective_start", "effective_end"),
    )


class PolicyRuleRevisionClaimModel(Base):
    __tablename__ = "policy_rule_revision_claims"

    rule_id: Mapped[str] = mapped_column(String(140), primary_key=True)
    rule_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(70), nullable=False)
    claim_revision: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["rule_id", "rule_revision"],
            ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision"],
            ondelete="RESTRICT",
            name="fk_policy_rule_claim_revision",
        ),
        ForeignKeyConstraint(
            ["claim_id", "claim_revision"],
            ["knowledge_claims.claim_id", "knowledge_claims.revision"],
            ondelete="RESTRICT",
            name="fk_policy_rule_source_claim",
        ),
        CheckConstraint("ordinal >= 0", name="ck_policy_rule_claim_ordinal"),
        UniqueConstraint(
            "rule_id", "rule_revision", "claim_id", "claim_revision",
            name="uq_policy_rule_claim_ref",
        ),
        Index("ix_policy_rule_claim_claim", "claim_id", "claim_revision"),
    )


class PolicyRuleRevisionEvidenceModel(Base):
    __tablename__ = "policy_rule_revision_evidence"

    rule_id: Mapped[str] = mapped_column(String(140), primary_key=True)
    rule_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
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
            ["rule_id", "rule_revision"],
            ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision"],
            ondelete="RESTRICT",
            name="fk_policy_rule_evidence_revision",
        ),
        CheckConstraint("ordinal >= 0", name="ck_policy_rule_evidence_ordinal"),
        CheckConstraint("length(source_url) > 0", name="ck_policy_rule_evidence_url"),
        CheckConstraint("locator_page IS NULL OR locator_page >= 1", name="ck_policy_rule_evidence_page"),
        CheckConstraint("locator_row IS NULL OR locator_row >= 1", name="ck_policy_rule_evidence_row"),
        Index("ix_policy_rule_evidence_observation", "source_observation_id"),
    )


class PolicyRuleRelationModel(Base):
    __tablename__ = "policy_rule_relations"

    rule_id: Mapped[str] = mapped_column(String(140), primary_key=True)
    rule_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    relation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_rule_id: Mapped[str] = mapped_column(String(140), nullable=False)
    target_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["rule_id", "rule_revision"],
            ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision"],
            ondelete="RESTRICT",
            name="fk_policy_rule_relation_source",
        ),
        ForeignKeyConstraint(
            ["target_rule_id", "target_revision", "target_hash"],
            [
                "policy_rule_revisions.rule_id",
                "policy_rule_revisions.revision",
                "policy_rule_revisions.content_hash",
            ],
            ondelete="RESTRICT",
            name="fk_policy_rule_relation_target_hash",
        ),
        ForeignKeyConstraint(
            ["rule_id", "rule_revision", "claim_ordinal"],
            [
                "policy_rule_revision_claims.rule_id",
                "policy_rule_revision_claims.rule_revision",
                "policy_rule_revision_claims.ordinal",
            ],
            ondelete="RESTRICT",
            name="fk_policy_rule_relation_claim",
        ),
        ForeignKeyConstraint(
            ["rule_id", "rule_revision", "evidence_ordinal"],
            [
                "policy_rule_revision_evidence.rule_id",
                "policy_rule_revision_evidence.rule_revision",
                "policy_rule_revision_evidence.ordinal",
            ],
            ondelete="RESTRICT",
            name="fk_policy_rule_relation_evidence",
        ),
        CheckConstraint("ordinal >= 0", name="ck_policy_rule_relation_ordinal"),
        CheckConstraint("claim_ordinal >= 0", name="ck_policy_rule_relation_claim_ordinal"),
        CheckConstraint("evidence_ordinal >= 0", name="ck_policy_rule_relation_evidence_ordinal"),
        CheckConstraint("length(target_hash) = 64", name="ck_policy_rule_relation_target_hash"),
        CheckConstraint(
            "(rule_id != target_rule_id) OR (rule_revision != target_revision)",
            name="ck_policy_rule_relation_not_self",
        ),
        CheckConstraint(
            "relation_kind IN ('exception_to', 'authorized_exception_to', 'overrides', 'supersedes', 'amends', 'requires')",
            name="ck_policy_rule_relation_kind",
        ),
        Index("ix_policy_rule_relation_target", "target_rule_id", "target_revision"),
    )


class PolicyApprovalEventModel(Base):
    __tablename__ = "policy_approval_events"

    event_id: Mapped[str] = mapped_column(String(88), primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(140), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    preview_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["rule_id", "revision"],
            ["policy_rule_revisions.rule_id", "policy_rule_revisions.revision"],
            ondelete="RESTRICT",
            name="fk_policy_approval_rule_revision",
        ),
        CheckConstraint(
            "event_id LIKE 'policy-approval-event:%'", name="ck_policy_approval_event_id_prefix"
        ),
        CheckConstraint("sequence >= 1", name="ck_policy_approval_sequence"),
        CheckConstraint("length(revision_hash) = 64", name="ck_policy_approval_revision_hash"),
        CheckConstraint(
            "kind IN ('pending_submitted', 'approved', 'rejected', 'withdrawn')",
            name="ck_policy_approval_kind",
        ),
        CheckConstraint(
            "(kind = 'pending_submitted' AND capability = 'policy.submit_revision') OR "
            "(kind != 'pending_submitted' AND capability = 'policy.approve_revision')",
            name="ck_policy_approval_capability_kind",
        ),
        CheckConstraint("length(reason) > 0", name="ck_policy_approval_reason"),
        CheckConstraint(
            "preview_fingerprint IS NULL OR length(preview_fingerprint) = 64",
            name="ck_policy_approval_preview_fingerprint",
        ),
        UniqueConstraint("rule_id", "revision", "sequence", name="uq_policy_approval_sequence"),
        Index("ix_policy_approval_history", "rule_id", "revision", "sequence"),
        Index("ix_policy_approval_actor_time", "actor_account_id", "recorded_at"),
    )


__all__ = [
    "PolicyApprovalEventModel",
    "PolicyRuleRelationModel",
    "PolicyRuleRevisionClaimModel",
    "PolicyRuleRevisionEvidenceModel",
    "PolicyRuleRevisionModel",
]
