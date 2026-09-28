from __future__ import annotations

import logging
from datetime import datetime

from andromeda.shared.contracts.errors import ConflictError, NotFoundError, ValidationError
from andromeda.shared.contracts.ids import AccountId, UniversityId, UniversityMembershipId

from ..contracts.public import MembershipStatus, UniversityAdminActor, UniversityAdminRole, UniversityMembership
from ..repository.ports import UniversityAdminAccessReader, UniversityMembershipWriter


logger = logging.getLogger("andromeda.modules.university_admin.membership")


class UniversityMembershipService:
    """Application policy for provisioning and owner-managed memberships."""

    def __init__(self, reader: UniversityAdminAccessReader, writer: UniversityMembershipWriter) -> None:
        self._reader = reader
        self._writer = writer

    def provision(
        self,
        *,
        membership_id: UniversityMembershipId,
        account_id: AccountId,
        university_id: UniversityId,
        role: UniversityAdminRole,
        granted_by_account_id: AccountId | None,
        now: datetime,
    ) -> UniversityMembership:
        membership = self._writer.upsert(
            membership_id=membership_id,
            account_id=account_id,
            university_id=university_id,
            role=role,
            granted_by_account_id=granted_by_account_id,
            now=now,
        )
        logger.info(
            "university_admin_membership_provisioned actor_kind=%s target_membership_id=%s university_id=%s operation=provision outcome=success",
            "ops" if granted_by_account_id is None else "account",
            membership.membership_id,
            university_id,
        )
        return membership

    def add_member(
        self,
        *,
        actor: UniversityAdminActor,
        membership_id: UniversityMembershipId,
        account_id: AccountId,
        role: UniversityAdminRole,
        now: datetime,
    ) -> UniversityMembership:
        if not actor.can(UniversityAdminRole.OWNER):
            raise ValidationError("Only an owner can manage memberships")
        if role is UniversityAdminRole.OWNER:
            raise ValidationError("Owner role is reserved for provisioning")
        return self.provision(
            membership_id=membership_id,
            account_id=account_id,
            university_id=actor.university_id,
            role=role,
            granted_by_account_id=actor.account_id,
            now=now,
        )

    def list_members(self, university_id: UniversityId) -> tuple[UniversityMembership, ...]:
        return self._reader.list_university_memberships(university_id, active_only=False)

    def revoke_member(
        self,
        *,
        actor: UniversityAdminActor,
        membership_id: UniversityMembershipId,
        expected_revision: int,
        now: datetime,
    ) -> UniversityMembership:
        if not actor.can(UniversityAdminRole.OWNER):
            raise ValidationError("Only an owner can manage memberships")
        target = self._reader.get_membership_by_id(membership_id)
        if target is None:
            raise NotFoundError("Resource was not found")
        if target.status is MembershipStatus.REVOKED:
            raise ConflictError("Membership is already revoked")
        if target.university_id != actor.university_id:
            raise NotFoundError("Resource was not found")
        return self._revoke_target(target, expected_revision=expected_revision, now=now, actor_kind="account")

    def revoke_by_operator(
        self,
        *,
        membership_id: UniversityMembershipId,
        expected_revision: int,
        now: datetime,
    ) -> UniversityMembership:
        target = self._reader.get_membership_by_id(membership_id)
        if target is None:
            raise NotFoundError("Resource was not found")
        return self._revoke_target(target, expected_revision=expected_revision, now=now, actor_kind="ops")

    def _revoke_target(
        self,
        target: UniversityMembership,
        *,
        expected_revision: int,
        now: datetime,
        actor_kind: str,
    ) -> UniversityMembership:
        if target.status is MembershipStatus.REVOKED:
            raise ConflictError("Membership is already revoked")
        if target.role is UniversityAdminRole.OWNER:
            active_owners = sum(
                item.status is MembershipStatus.ACTIVE and item.role is UniversityAdminRole.OWNER
                for item in self._reader.list_university_memberships(target.university_id, active_only=True)
            )
            if active_owners <= 1:
                raise ConflictError("The last active owner cannot be revoked")
        membership = self._writer.revoke(
            membership_id=target.membership_id,
            expected_revision=expected_revision,
            now=now,
        )
        logger.info(
            "university_admin_membership_revoked actor_kind=%s target_membership_id=%s university_id=%s operation=revoke outcome=success",
            actor_kind,
            target.membership_id,
            target.university_id,
        )
        return membership


__all__ = ["UniversityMembershipService"]
