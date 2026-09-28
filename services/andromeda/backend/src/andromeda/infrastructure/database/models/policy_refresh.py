"""Persistence for targeted policy projection refresh state and attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class PolicyProjectionRefreshModel(Base):
    __tablename__ = "policy_projection_refresh_state"

    refresh_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    target_object_id: Mapped[str] = mapped_column(String(320), nullable=False)
    target_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_owner_module: Mapped[str | None] = mapped_column(String(64), nullable=True)
    projection_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    invalidated_by_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON().with_variant(cast(Any, JSONB)(), "postgresql"), nullable=False
    )
    invalidation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    projection_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint("refresh_key LIKE 'policy-refresh:%'", name="ck_policy_refresh_key_prefix"),
        CheckConstraint(
            "target_kind IN ('policy_rule', 'domain_rule', 'scope')",
            name="ck_policy_refresh_target_kind",
        ),
        CheckConstraint(
            "(target_kind = 'policy_rule' AND target_revision IS NOT NULL AND "
            "target_content_hash IS NOT NULL AND target_owner_module IS NULL) OR "
            "(target_kind = 'domain_rule' AND target_revision IS NOT NULL AND "
            "target_content_hash IS NULL AND target_owner_module IS NOT NULL) OR "
            "(target_kind = 'scope' AND target_revision IS NULL AND "
            "target_content_hash IS NULL AND target_owner_module IS NULL)",
            name="ck_policy_refresh_target_shape",
        ),
        CheckConstraint(
            "projection_kind IN ('effective_policy', 'domain_impact', 'dependency_closure')",
            name="ck_policy_refresh_projection_kind",
        ),
        CheckConstraint("generation >= 1", name="ck_policy_refresh_generation"),
        CheckConstraint(
            "completed_generation >= 0 AND completed_generation <= generation",
            name="ck_policy_refresh_completed_generation",
        ),
        CheckConstraint("length(invalidation_fingerprint) = 64", name="ck_policy_refresh_fingerprint"),
        CheckConstraint("state IN ('dirty', 'ready', 'failed')", name="ck_policy_refresh_state"),
        CheckConstraint(
            "(state = 'ready' AND completed_generation = generation AND "
            "projection_version IS NOT NULL AND last_success_at IS NOT NULL AND failure_code IS NULL) OR "
            "(state = 'dirty' AND completed_generation < generation AND failure_code IS NULL) OR "
            "(state = 'failed' AND completed_generation < generation AND failure_code IS NOT NULL)",
            name="ck_policy_refresh_state_generation",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_policy_refresh_attempt_count"),
        Index("ix_policy_projection_refresh_pending", "state", "last_updated_at"),
        Index("ix_policy_projection_refresh_target", "target_kind", "target_object_id"),
    )


class PolicyProjectionRefreshAttemptModel(Base):
    __tablename__ = "policy_projection_refresh_attempts"

    attempt_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    refresh_key: Mapped[str] = mapped_column(
        ForeignKey("policy_projection_refresh_state.refresh_key", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    projection_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "attempt_id LIKE 'policy-refresh-attempt:%'", name="ck_policy_refresh_attempt_id_prefix"
        ),
        CheckConstraint("sequence >= 1", name="ck_policy_refresh_attempt_sequence"),
        CheckConstraint("generation >= 1", name="ck_policy_refresh_attempt_generation"),
        CheckConstraint(
            "(outcome = 'completed' AND projection_version IS NOT NULL AND failure_code IS NULL) OR "
            "(outcome = 'failed' AND projection_version IS NULL AND failure_code IS NOT NULL) OR "
            "(outcome = 'stale_result_rejected' AND projection_version IS NOT NULL AND failure_code IS NOT NULL)",
            name="ck_policy_refresh_attempt_result",
        ),
        UniqueConstraint("refresh_key", "sequence", name="uq_policy_refresh_attempt_sequence"),
        Index("ix_policy_refresh_attempt_history", "refresh_key", "sequence"),
    )


__all__ = ["PolicyProjectionRefreshAttemptModel", "PolicyProjectionRefreshModel"]
