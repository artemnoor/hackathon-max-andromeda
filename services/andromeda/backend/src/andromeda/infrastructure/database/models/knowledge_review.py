"""Immutable human review action audit for source-backed knowledge candidates."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class KnowledgeReviewActionModel(Base):
    __tablename__ = "knowledge_review_actions"

    event_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(84), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[str] = mapped_column(String(140), nullable=False)
    target_revision: Mapped[int] = mapped_column(nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    result_id: Mapped[str] = mapped_column(String(140), nullable=False)
    result_revision: Mapped[int] = mapped_column(nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    related_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    related_id: Mapped[str | None] = mapped_column(String(140), nullable=True)
    related_revision: Mapped[int | None] = mapped_column(nullable=True)
    related_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "event_id LIKE 'knowledge-review-action:%'",
            name="ck_knowledge_review_action_id_prefix",
        ),
        CheckConstraint(
            "idempotency_key LIKE 'review-idempotency:%'",
            name="ck_knowledge_review_idempotency_prefix",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND length(target_hash) = 64 AND "
            "length(result_hash) = 64",
            name="ck_knowledge_review_hash_lengths",
        ),
        CheckConstraint(
            "target_kind IN ('claim', 'change_event') AND "
            "((target_kind = 'claim' AND target_id LIKE 'claim:%') OR "
            "(target_kind = 'change_event' AND target_id LIKE 'change-event:%'))",
            name="ck_knowledge_review_target_kind",
        ),
        CheckConstraint("target_revision >= 1", name="ck_knowledge_review_target_revision"),
        CheckConstraint(
            "result_id = target_id AND result_revision = target_revision + 1",
            name="ck_knowledge_review_result_revision",
        ),
        CheckConstraint(
            "action IN ('approve', 'reject', 'edit', 'merge', 'resolve_identity', "
            "'mark_unresolved', 'mark_duplicate')",
            name="ck_knowledge_review_action_kind",
        ),
        CheckConstraint(
            "(action IN ('merge', 'mark_duplicate') AND related_kind = target_kind AND "
            "related_id IS NOT NULL AND related_revision IS NOT NULL AND "
            "related_hash IS NOT NULL) OR "
            "(action NOT IN ('merge', 'mark_duplicate') AND related_kind IS NULL AND "
            "related_id IS NULL AND related_revision IS NULL AND related_hash IS NULL)",
            name="ck_knowledge_review_related_target",
        ),
        CheckConstraint(
            "(action = 'edit' AND capability = 'knowledge.edit_candidate') OR "
            "(action = 'resolve_identity' AND capability = 'knowledge.resolve_identity') OR "
            "(action NOT IN ('edit', 'resolve_identity') AND "
            "capability = 'knowledge.review_candidate')",
            name="ck_knowledge_review_capability",
        ),
        CheckConstraint("length(reason) > 0", name="ck_knowledge_review_reason"),
        UniqueConstraint(
            "actor_account_id",
            "idempotency_key",
            name="uq_knowledge_review_actor_idempotency",
        ),
        Index("ix_knowledge_review_target_history", "target_kind", "target_id", "recorded_at"),
        Index("ix_knowledge_review_actor_time", "actor_account_id", "recorded_at"),
    )


__all__ = ["KnowledgeReviewActionModel"]
