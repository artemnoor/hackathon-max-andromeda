from __future__ import annotations

from datetime import datetime
from typing import Protocol

from andromeda.shared.contracts.ids import AccountId, UniversityId, UniversityMembershipId

from ..contracts.public import (
    MembershipStatus,
    UniversityAdminRole,
    UniversityMembership,
)


class UniversityAdminAccessReader(Protocol):
    def get_membership_by_id(self, membership_id: UniversityMembershipId) -> UniversityMembership | None: ...

    def get_membership(self, account_id: AccountId, university_id: UniversityId) -> UniversityMembership | None: ...

    def list_memberships(self, account_id: AccountId) -> tuple[UniversityMembership, ...]: ...

    def list_university_memberships(
        self, university_id: UniversityId, *, active_only: bool = False
    ) -> tuple[UniversityMembership, ...]: ...


class UniversityMembershipWriter(Protocol):
    def upsert(
        self,
        *,
        membership_id: UniversityMembershipId,
        account_id: AccountId,
        university_id: UniversityId,
        role: UniversityAdminRole,
        granted_by_account_id: AccountId | None,
        now: datetime,
    ) -> UniversityMembership: ...

    def revoke(
        self,
        *,
        membership_id: UniversityMembershipId,
        expected_revision: int,
        now: datetime,
    ) -> UniversityMembership: ...


__all__ = ["UniversityAdminAccessReader", "UniversityMembershipWriter", "MembershipStatus"]
