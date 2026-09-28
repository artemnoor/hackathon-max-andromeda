from __future__ import annotations

from datetime import datetime, timezone

import pytest

from andromeda.modules.university_admin.contracts.public import (
    MembershipStatus,
    UniversityAdminRole,
    UniversityMembership,
)
from andromeda.modules.university_admin.services.access import UniversityAdminAccessService
from andromeda.shared.contracts.errors import ForbiddenError, NotFoundError


ACCOUNT_ID = "account:" + "a" * 32
UNIVERSITY_ID = "university:bmstu"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _membership(role: UniversityAdminRole, status: MembershipStatus = MembershipStatus.ACTIVE) -> UniversityMembership:
    return UniversityMembership(
        membershipId="membership:" + "a" * 32,
        accountId=ACCOUNT_ID,
        universityId=UNIVERSITY_ID,
        role=role,
        status=status,
        revision=1,
        createdAt=NOW,
        updatedAt=NOW,
        revokedAt=NOW if status is MembershipStatus.REVOKED else None,
    )


class _Reader:
    def __init__(self, membership: UniversityMembership | None) -> None:
        self.membership = membership

    def get_membership(self, account_id: str, university_id: str) -> UniversityMembership | None:
        return self.membership if account_id == ACCOUNT_ID and university_id == UNIVERSITY_ID else None

    def list_memberships(self, account_id: str) -> tuple[UniversityMembership, ...]:
        return (self.membership,) if self.membership is not None and account_id == ACCOUNT_ID else ()


def test_access_service_resolves_role_hierarchy() -> None:
    service = UniversityAdminAccessService(_Reader(_membership(UniversityAdminRole.OWNER)))

    actor = service.require(ACCOUNT_ID, UNIVERSITY_ID, UniversityAdminRole.EDITOR)

    assert actor.role is UniversityAdminRole.OWNER
    assert actor.can(UniversityAdminRole.VIEWER)


def test_access_service_returns_forbidden_for_insufficient_active_role() -> None:
    service = UniversityAdminAccessService(_Reader(_membership(UniversityAdminRole.VIEWER)))

    with pytest.raises(ForbiddenError) as error:
        service.require(ACCOUNT_ID, UNIVERSITY_ID, UniversityAdminRole.EDITOR)

    assert error.value.code.value == "FORBIDDEN"


def test_access_service_hides_missing_and_revoked_scopes() -> None:
    for membership in (None, _membership(UniversityAdminRole.OWNER, MembershipStatus.REVOKED)):
        service = UniversityAdminAccessService(_Reader(membership))
        with pytest.raises(NotFoundError):
            service.require(ACCOUNT_ID, UNIVERSITY_ID)
