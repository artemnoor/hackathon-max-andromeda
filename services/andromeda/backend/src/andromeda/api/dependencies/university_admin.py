from __future__ import annotations

from fastapi import Depends

from andromeda.api.dependencies.auth_session import require_current_account
from andromeda.api.dependencies.services import get_university_admin_access_service
from andromeda.modules.auth.contracts.public import Account
from andromeda.modules.university_admin.contracts.public import UniversityAdminActor, UniversityAdminRole
from andromeda.modules.university_admin.services.access import UniversityAdminAccessService
from andromeda.shared.contracts.ids import UniversityId


def require_university_admin(
    university_id: UniversityId,
    account: Account = Depends(require_current_account),
    service: UniversityAdminAccessService = Depends(get_university_admin_access_service),
) -> UniversityAdminActor:
    return service.require(account.account_id, university_id, UniversityAdminRole.VIEWER)


def require_university_editor(
    university_id: UniversityId,
    account: Account = Depends(require_current_account),
    service: UniversityAdminAccessService = Depends(get_university_admin_access_service),
) -> UniversityAdminActor:
    return service.require(account.account_id, university_id, UniversityAdminRole.EDITOR)


def require_university_owner(
    university_id: UniversityId,
    account: Account = Depends(require_current_account),
    service: UniversityAdminAccessService = Depends(get_university_admin_access_service),
) -> UniversityAdminActor:
    return service.require(account.account_id, university_id, UniversityAdminRole.OWNER)


__all__ = ["require_university_admin", "require_university_editor", "require_university_owner"]
