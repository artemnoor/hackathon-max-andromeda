from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class KnowledgeManualSubmissionModel(Base):
    """Immutable attribution for operator-provided candidates and snapshots."""

    __tablename__ = "knowledge_manual_submissions"

    submission_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=False
    )
    university_id: Mapped[str | None] = mapped_column(
        ForeignKey("universities.id", ondelete="RESTRICT"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(String(140), nullable=False)
    target_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_observation_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_source_observations.source_observation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "actor_account_id", "idempotency_key", name="uq_knowledge_manual_actor_idempotency"
        ),
        CheckConstraint(
            "submission_id LIKE 'knowledge-manual-submission:%'",
            name="ck_knowledge_manual_submission_id_prefix",
        ),
        CheckConstraint(
            "kind IN ('source_snapshot', 'claim_candidate')",
            name="ck_knowledge_manual_submission_kind",
        ),
        CheckConstraint("length(idempotency_key) = 64", name="ck_knowledge_manual_idempotency_hash"),
        CheckConstraint(
            "length(request_fingerprint) = 64 AND length(target_hash) = 64",
            name="ck_knowledge_manual_content_hashes",
        ),
        CheckConstraint("target_revision >= 1", name="ck_knowledge_manual_target_revision"),
        CheckConstraint("length(reason) > 0", name="ck_knowledge_manual_reason"),
        CheckConstraint(
            "(kind = 'source_snapshot' AND target_id LIKE 'source-observation:%') OR "
            "(kind = 'claim_candidate' AND target_id LIKE 'claim:%' AND university_id IS NOT NULL)",
            name="ck_knowledge_manual_target_kind",
        ),
        Index("ix_knowledge_manual_target_history", "target_id", "target_revision", "recorded_at"),
        Index("ix_knowledge_manual_university_time", "university_id", "recorded_at"),
    )
