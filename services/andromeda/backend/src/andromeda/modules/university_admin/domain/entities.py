from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import AccountId, UniversityId, UniversityMembershipId


class UniversityAdminRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class UniversityMembership(ContractModel):
    membership_id: UniversityMembershipId = Field(alias="membershipId")
    account_id: AccountId = Field(alias="accountId")
    university_id: UniversityId = Field(alias="universityId")
    role: UniversityAdminRole
    status: MembershipStatus
    revision: int = Field(ge=1)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    granted_by_account_id: AccountId | None = Field(default=None, alias="grantedByAccountId")
    revoked_at: datetime | None = Field(default=None, alias="revokedAt")

    @model_validator(mode="after")
    def validate_dates(self) -> UniversityMembership:
        for name, value in (("created_at", self.created_at), ("updated_at", self.updated_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"membership {name} must be timezone-aware")
        if self.revoked_at is not None and (self.revoked_at.tzinfo is None or self.revoked_at.utcoffset() is None):
            raise ValueError("membership revoked_at must be timezone-aware")
        if self.status is MembershipStatus.ACTIVE and self.revoked_at is not None:
            raise ValueError("active membership cannot have revoked_at")
        if self.status is MembershipStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked membership must have revoked_at")
        return self


class UniversityAdminActor(ContractModel):
    account_id: AccountId = Field(alias="accountId")
    university_id: UniversityId = Field(alias="universityId")
    membership_id: UniversityMembershipId = Field(alias="membershipId")
    role: UniversityAdminRole
    revision: int = Field(ge=1)

    def can(self, required: UniversityAdminRole) -> bool:
        order = {
            UniversityAdminRole.VIEWER: 1,
            UniversityAdminRole.EDITOR: 2,
            UniversityAdminRole.OWNER: 3,
        }
        return order[self.role] >= order[required]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "MembershipStatus",
    "UniversityAdminActor",
    "UniversityAdminRole",
    "UniversityMembership",
    "utc_now",
]
