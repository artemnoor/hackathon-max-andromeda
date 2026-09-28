from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class QuerySessionModel(Base):
    """Owner-bound generic conversation state; credentials never enter JSON."""

    __tablename__ = "query_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_key: Mapped[str] = mapped_column(String(320), nullable=False)
    session_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_query_sessions_owner_updated", "owner_key", "updated_at"),
        Index("ix_query_sessions_expiry", "expires_at"),
        CheckConstraint("length(session_id) > 0", name="ck_query_session_id_non_empty"),
        CheckConstraint("length(owner_key) > 0", name="ck_query_session_owner_non_empty"),
        CheckConstraint("revision >= 1", name="ck_query_session_revision_positive"),
        CheckConstraint("expires_at > updated_at", name="ck_query_session_expiry_after_update"),
        CheckConstraint(
            "(account_id IS NOT NULL AND session_key_hash IS NULL) OR (account_id IS NULL AND session_key_hash IS NOT NULL)",
            name="ck_query_session_owner_identity",
        ),
    )


__all__ = ["QuerySessionModel"]
