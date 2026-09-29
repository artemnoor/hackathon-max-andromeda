from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, TypeVar

from pydantic import BeforeValidator, Field

from andromeda.modules.university_admin.contracts.public import MembershipStatus, UniversityAdminRole, UniversityMembership
from andromeda.shared.contracts.ids import AccountId, UniversityId, UniversityMembershipId

from .common import ApiModel


EnumT = TypeVar("EnumT", bound=Enum)


def _enum_from_json(enum_type: type[EnumT], value: object) -> EnumT:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        return enum_type(value)
    raise TypeError(f"{enum_type.__name__} must be a string")


def _admin_role_from_json(value: object) -> UniversityAdminRole:
    return _enum_from_json(UniversityAdminRole, value)


JsonAdminRole = Annotated[UniversityAdminRole, BeforeValidator(_admin_role_from_json)]


class UniversityMembershipResponse(ApiModel):
    membership_id: UniversityMembershipId = Field(alias="membershipId")
    account_id: AccountId = Field(alias="accountId")
    university_id: UniversityId = Field(alias="universityId")
    university_name: str | None = Field(default=None, min_length=1, max_length=512, alias="universityName")
    role: JsonAdminRole
    status: MembershipStatus
    revision: int = Field(strict=True, ge=1)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    revoked_at: datetime | None = Field(default=None, alias="revokedAt")


class UniversityMembershipListResponse(ApiModel):
    items: tuple[UniversityMembershipResponse, ...] = ()


class UniversityMembershipProvisionRequest(ApiModel):
    account_id: AccountId = Field(alias="accountId")
    university_id: UniversityId = Field(alias="universityId")
    role: JsonAdminRole


class UniversityMembershipOwnerRequest(ApiModel):
    account_id: AccountId = Field(alias="accountId")
    role: JsonAdminRole


class UniversityMembershipRevokeQuery(ApiModel):
    expected_revision: int = Field(strict=True, ge=1, alias="expectedRevision")


def membership_response(
    membership: UniversityMembership,
    *,
    university_name: str | None = None,
) -> UniversityMembershipResponse:
    return UniversityMembershipResponse(
        membershipId=membership.membership_id,
        accountId=membership.account_id,
        universityId=membership.university_id,
        universityName=university_name,
        role=membership.role,
        status=membership.status,
        revision=membership.revision,
        createdAt=membership.created_at,
        updatedAt=membership.updated_at,
        revokedAt=membership.revoked_at,
    )


__all__ = [
    "UniversityMembershipListResponse",
    "UniversityMembershipOwnerRequest",
    "UniversityMembershipProvisionRequest",
    "UniversityMembershipResponse",
    "UniversityMembershipRevokeQuery",
    "membership_response",
]
