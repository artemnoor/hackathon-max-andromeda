from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, status

from andromeda.api.dependencies import (
    get_university_admin_access_service,
    get_university_membership_service,
    get_university_reader,
    require_ops_access,
)
from andromeda.api.dependencies.auth_session import get_auth_repository, require_current_account
from andromeda.api.dependencies.university_admin import require_university_editor, require_university_owner
from andromeda.api.schemas.university_admin import (
    UniversityMembershipListResponse,
    UniversityMembershipOwnerRequest,
    UniversityMembershipProvisionRequest,
    UniversityMembershipResponse,
    membership_response,
)
from andromeda.modules.auth.contracts.public import Account
from andromeda.modules.auth.repository.ports import AccountRepository
from andromeda.modules.university_admin.contracts.public import MembershipStatus, UniversityAdminActor, UniversityAdminRole
from andromeda.modules.university_admin.services.access import UniversityAdminAccessService
from andromeda.modules.university_admin.services.membership import UniversityMembershipService
from andromeda.modules.universities.repository.ports import UniversityReader
from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.ids import UniversityId, UniversityMembershipId


router = APIRouter(tags=["university-admin"])


@router.get(
    "/university-admin/memberships",
    response_model=UniversityMembershipListResponse,
    operation_id="list_current_university_memberships",
)
def list_current_memberships(
    account: Account = Depends(require_current_account),
    access: UniversityAdminAccessService = Depends(get_university_admin_access_service),
    universities: UniversityReader = Depends(get_university_reader),
) -> UniversityMembershipListResponse:
    memberships = tuple(
        item
        for item in access.list_memberships(account.account_id)
        if item.status is MembershipStatus.ACTIVE
    )
    return UniversityMembershipListResponse(
        items=tuple(
            membership_response(item, university_name=_university_name(universities, item.university_id))
            for item in memberships
        )
    )


@router.post(
    "/ops/university-admin/members",
    response_model=UniversityMembershipResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="provision_university_admin_membership",
    dependencies=[Depends(require_ops_access)],
)
def provision_membership(
    body: UniversityMembershipProvisionRequest,
    service: UniversityMembershipService = Depends(get_university_membership_service),
    account_repository: AccountRepository = Depends(get_auth_repository),
    universities: UniversityReader = Depends(get_university_reader),
) -> UniversityMembershipResponse:
    if account_repository.get_by_id(body.account_id) is None or universities.get(body.university_id) is None:
        raise NotFoundError("Resource was not found")
    membership = service.provision(
        membership_id="membership:" + uuid4().hex,
        account_id=body.account_id,
        university_id=body.university_id,
        role=body.role,
        granted_by_account_id=None,
        now=datetime.now(timezone.utc),
    )
    return membership_response(membership, university_name=_university_name(universities, membership.university_id))


@router.delete(
    "/ops/university-admin/members/{membership_id}",
    response_model=UniversityMembershipResponse,
    operation_id="revoke_provisioned_university_admin_membership",
    dependencies=[Depends(require_ops_access)],
)
def revoke_provisioned_membership(
    membership_id: UniversityMembershipId,
    expected_revision: int = Query(alias="expectedRevision", ge=1),
    service: UniversityMembershipService = Depends(get_university_membership_service),
    universities: UniversityReader = Depends(get_university_reader),
) -> UniversityMembershipResponse:
    membership = service.revoke_by_operator(
        membership_id=membership_id,
        expected_revision=expected_revision,
        now=datetime.now(timezone.utc),
    )
    return membership_response(membership, university_name=_university_name(universities, membership.university_id))


@router.get(
    "/university-admin/universities/{university_id}/members",
    response_model=UniversityMembershipListResponse,
    operation_id="list_university_admin_members",
)
def list_university_members(
    university_id: UniversityId,
    _actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityMembershipService = Depends(get_university_membership_service),
    universities: UniversityReader = Depends(get_university_reader),
) -> UniversityMembershipListResponse:
    members = service.list_members(university_id)
    university_name = _university_name(universities, university_id)
    return UniversityMembershipListResponse(
        items=tuple(membership_response(item, university_name=university_name) for item in members)
    )


@router.post(
    "/university-admin/universities/{university_id}/members",
    response_model=UniversityMembershipResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="add_university_admin_member",
)
def add_university_member(
    body: UniversityMembershipOwnerRequest,
    university_id: UniversityId,
    actor: UniversityAdminActor = Depends(require_university_owner),
    service: UniversityMembershipService = Depends(get_university_membership_service),
    account_repository: AccountRepository = Depends(get_auth_repository),
    universities: UniversityReader = Depends(get_university_reader),
) -> UniversityMembershipResponse:
    if account_repository.get_by_id(body.account_id) is None:
        raise NotFoundError("Resource was not found")
    membership = service.add_member(
        actor=actor,
        membership_id="membership:" + uuid4().hex,
        account_id=body.account_id,
        role=body.role,
        now=datetime.now(timezone.utc),
    )
    return membership_response(membership, university_name=_university_name(universities, university_id))


@router.delete(
    "/university-admin/universities/{university_id}/members/{membership_id}",
    response_model=UniversityMembershipResponse,
    operation_id="revoke_university_admin_member",
)
def revoke_university_member(
    university_id: UniversityId,
    membership_id: UniversityMembershipId,
    expected_revision: int = Query(alias="expectedRevision", ge=1),
    actor: UniversityAdminActor = Depends(require_university_owner),
    service: UniversityMembershipService = Depends(get_university_membership_service),
    universities: UniversityReader = Depends(get_university_reader),
) -> UniversityMembershipResponse:
    membership = service.revoke_member(
        actor=actor,
        membership_id=membership_id,
        expected_revision=expected_revision,
        now=datetime.now(timezone.utc),
    )
    if membership.university_id != university_id:
        raise NotFoundError("Resource was not found")
    return membership_response(membership, university_name=_university_name(universities, university_id))


def _university_name(universities: UniversityReader, university_id: UniversityId) -> str | None:
    university = universities.get(university_id)
    return university.name if university is not None else None


__all__ = ["router"]
