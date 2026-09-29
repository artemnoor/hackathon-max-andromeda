from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class UniversityAdminMembershipModel(Base):
    __tablename__ = "university_admin_memberships"

    membership_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), ForeignKey("accounts.account_id"), nullable=False)
    university_id: Mapped[str] = mapped_column(ForeignKey("universities.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    granted_by_account_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("accounts.account_id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("account_id", "university_id", name="uq_university_admin_membership_scope"),
        Index("ix_university_admin_memberships_university_status", "university_id", "status"),
        CheckConstraint("membership_id LIKE 'membership:%'", name="ck_university_admin_membership_id"),
        CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_university_admin_membership_role"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_university_admin_membership_status"),
        CheckConstraint("revision >= 1", name="ck_university_admin_membership_revision"),
        CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR (status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_university_admin_membership_revocation",
        ),
    )
