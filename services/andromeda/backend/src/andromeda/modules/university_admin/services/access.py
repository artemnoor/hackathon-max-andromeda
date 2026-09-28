from __future__ import annotations

import logging

from andromeda.shared.contracts.errors import ForbiddenError, NotFoundError
from andromeda.shared.contracts.ids import AccountId, UniversityId

from ..contracts.public import UniversityAdminActor, UniversityAdminRole, UniversityMembership
from ..repository.ports import UniversityAdminAccessReader


logger = logging.getLogger("andromeda.modules.university_admin.access")


class UniversityAdminAccessService:
    def __init__(self, reader: UniversityAdminAccessReader) -> None:
        self._reader = reader

    def list_memberships(self, account_id: AccountId) -> tuple[UniversityMembership, ...]:
        memberships = self._reader.list_memberships(account_id)
        logger.debug(
            "university_admin_memberships_listed account_id=%s active_count=%d",
            account_id,
            sum(item.status.value == "active" for item in memberships),
        )
        return memberships

    def resolve(self, account_id: AccountId, university_id: UniversityId) -> UniversityAdminActor | None:
        membership = self._reader.get_membership(account_id, university_id)
        if membership is None or membership.status.value != "active":
            logger.warning(
                "university_admin_access_denied account_id=%s university_id=%s reason=membership_missing",
                account_id,
                university_id,
            )
            return None
        actor = UniversityAdminActor(
            accountId=membership.account_id,
            universityId=membership.university_id,
            membershipId=membership.membership_id,
            role=membership.role,
            revision=membership.revision,
        )
        logger.debug(
            "university_admin_access_resolved account_id=%s university_id=%s role=%s revision=%d",
            account_id,
            university_id,
            actor.role.value,
            actor.revision,
        )
        return actor

    def require(
        self,
        account_id: AccountId,
        university_id: UniversityId,
        minimum_role: UniversityAdminRole = UniversityAdminRole.VIEWER,
    ) -> UniversityAdminActor:
        actor = self.resolve(account_id, university_id)
        if actor is None:
            raise NotFoundError("Resource was not found")
        if not actor.can(minimum_role):
            logger.warning(
                "university_admin_access_denied account_id=%s university_id=%s role=%s required=%s reason=insufficient_role",
                account_id,
                university_id,
                actor.role.value,
                minimum_role.value,
            )
            raise ForbiddenError()
        return actor


__all__ = ["UniversityAdminAccessService"]
