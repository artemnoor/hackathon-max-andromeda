from __future__ import annotations

from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from andromeda.modules.university_admin.contracts.public import (
    MembershipStatus,
    UniversityAdminRole,
    UniversityMembership,
)
from andromeda.modules.university_admin.repository.ports import (
    UniversityAdminAccessReader,
    UniversityMembershipWriter,
)
from andromeda.shared.contracts.errors import ConflictError, NotFoundError
from andromeda.shared.contracts.ids import AccountId, UniversityId, UniversityMembershipId

from ..database.models import UniversityAdminMembershipModel


logger = logging.getLogger("andromeda.infrastructure.repositories.university_admin")


class SqlAlchemyUniversityAdminMembershipRepository(UniversityAdminAccessReader, UniversityMembershipWriter):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_membership(self, account_id: AccountId, university_id: UniversityId) -> UniversityMembership | None:
        model = self._session.scalar(
            select(UniversityAdminMembershipModel).where(
                UniversityAdminMembershipModel.account_id == account_id,
                UniversityAdminMembershipModel.university_id == university_id,
            )
        )
        return _to_membership(model) if model is not None else None

    def get_membership_by_id(self, membership_id: UniversityMembershipId) -> UniversityMembership | None:
        model = self._session.get(UniversityAdminMembershipModel, membership_id)
        return _to_membership(model) if model is not None else None

    def list_memberships(self, account_id: AccountId) -> tuple[UniversityMembership, ...]:
        models = self._session.scalars(
            select(UniversityAdminMembershipModel)
            .where(UniversityAdminMembershipModel.account_id == account_id)
            .order_by(UniversityAdminMembershipModel.university_id)
        ).all()
        return tuple(_to_membership(model) for model in models)

    def list_university_memberships(
        self, university_id: UniversityId, *, active_only: bool = False
    ) -> tuple[UniversityMembership, ...]:
        statement = select(UniversityAdminMembershipModel).where(
            UniversityAdminMembershipModel.university_id == university_id
        )
        if active_only:
            statement = statement.where(UniversityAdminMembershipModel.status == MembershipStatus.ACTIVE.value)
        models = self._session.scalars(
            statement.order_by(UniversityAdminMembershipModel.created_at, UniversityAdminMembershipModel.membership_id)
        ).all()
        return tuple(_to_membership(model) for model in models)

    def upsert(
        self,
        *,
        membership_id: UniversityMembershipId,
        account_id: AccountId,
        university_id: UniversityId,
        role: UniversityAdminRole,
        granted_by_account_id: AccountId | None,
        now: datetime,
    ) -> UniversityMembership:
        current = self._session.scalar(
            select(UniversityAdminMembershipModel).where(
                UniversityAdminMembershipModel.account_id == account_id,
                UniversityAdminMembershipModel.university_id == university_id,
            )
        )
        timestamp = _utc(now)
        if current is None:
            current = UniversityAdminMembershipModel(
                membership_id=membership_id,
                account_id=account_id,
                university_id=university_id,
                role=role.value,
                status=MembershipStatus.ACTIVE.value,
                revision=1,
                created_at=timestamp,
                updated_at=timestamp,
                granted_by_account_id=granted_by_account_id,
                revoked_at=None,
            )
            self._session.add(current)
        else:
            current.role = role.value
            current.status = MembershipStatus.ACTIVE.value
            current.revision += 1
            current.updated_at = timestamp
            current.granted_by_account_id = granted_by_account_id
            current.revoked_at = None
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            logger.info(
                "university_admin_membership_write_rejected operation=upsert account_id=%s university_id=%s outcome=conflict",
                account_id,
                university_id,
            )
            raise ConflictError("Membership could not be created") from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.error("university_admin_membership_write_failed operation=upsert")
            raise RuntimeError("Membership persistence failed") from exc
        return _to_membership(current)

    def revoke(
        self,
        *,
        membership_id: UniversityMembershipId,
        expected_revision: int,
        now: datetime,
    ) -> UniversityMembership:
        model = self._session.get(UniversityAdminMembershipModel, membership_id)
        if model is None:
            raise NotFoundError("Resource was not found")
        if model.revision != expected_revision:
            raise ConflictError("Membership revision is stale")
        model.status = MembershipStatus.REVOKED.value
        model.revision += 1
        model.updated_at = _utc(now)
        model.revoked_at = _utc(now)
        try:
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.error("university_admin_membership_write_failed operation=revoke")
            raise RuntimeError("Membership revocation failed") from exc
        return _to_membership(model)


def _to_membership(model: UniversityAdminMembershipModel) -> UniversityMembership:
    return UniversityMembership(
        membershipId=model.membership_id,
        accountId=model.account_id,
        universityId=model.university_id,
        role=UniversityAdminRole(model.role),
        status=MembershipStatus(model.status),
        revision=model.revision,
        createdAt=_utc(model.created_at),
        updatedAt=_utc(model.updated_at),
        grantedByAccountId=model.granted_by_account_id,
        revokedAt=_utc(model.revoked_at) if model.revoked_at is not None else None,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = ["SqlAlchemyUniversityAdminMembershipRepository"]
