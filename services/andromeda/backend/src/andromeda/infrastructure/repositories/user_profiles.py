"""SQLAlchemy adapter for the public UserProfile persistence port."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from andromeda.modules.proftest.contracts.public import ProfileScope, UserProfile, UserProfileSnapshot
from andromeda.modules.proftest.repository.ports import ProfileBindingOutcome, ProfileBindingPort, UserProfileRepository
from andromeda.shared.contracts.ids import AccountId
from andromeda.shared.contracts.errors import ConflictError, ContractError, ErrorCode, NotFoundError

from ..database.models import UserProfileModel


logger = logging.getLogger("andromeda.infrastructure.repositories.user_profiles")


class SqlAlchemyUserProfileRepository(UserProfileRepository, ProfileBindingPort):
    """Persist exactly one current snapshot for each account or anonymous scope."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_current(self, scope: ProfileScope) -> UserProfileSnapshot | None:
        logger.debug("user_profile_read_start operation=get_current dialect=%s", self._dialect)
        model = self._find(scope)
        if model is None:
            logger.warning("user_profile_read_empty outcome=missing")
            return None
        if _utc(model.expires_at) <= _now():
            logger.warning("user_profile_read_empty outcome=expired")
            return None
        snapshot = self._to_snapshot(model)
        logger.debug("user_profile_read_complete outcome=found revision=%d", snapshot.revision)
        return snapshot

    def create(self, scope: ProfileScope, profile: UserProfile, *, expires_at: datetime) -> UserProfileSnapshot:
        logger.debug("user_profile_write_start operation=create")
        existing = self._find(scope)
        if existing is not None and _utc(existing.expires_at) > _now():
            logger.warning("user_profile_write_rejected operation=create outcome=duplicate")
            raise ConflictError("Current profile already exists")

        now = _now()
        values = self._values(scope, profile, revision=1, created_at=now, updated_at=now, expires_at=expires_at)
        try:
            if existing is None:
                model = UserProfileModel(**values)
                self._session.add(model)
            else:
                model = existing
                self._replace(model, values)
            self._session.flush()
            snapshot = self._to_snapshot(model)
            self._session.commit()
        except IntegrityError as exc:
            self._rollback("create", exc)
            logger.warning("user_profile_write_rejected operation=create outcome=duplicate")
            raise ConflictError("Current profile already exists") from exc
        except SQLAlchemyError as exc:
            self._rollback("create", exc)
            raise
        logger.info("user_profile_write_complete operation=create revision=%d", snapshot.revision)
        return snapshot

    def update(
        self,
        scope: ProfileScope,
        profile: UserProfile,
        *,
        expected_revision: int,
        expires_at: datetime,
    ) -> UserProfileSnapshot:
        logger.debug("user_profile_write_start operation=update expected_revision=%d", expected_revision)
        model = self._active_model(scope)
        if model is None:
            raise NotFoundError("Current profile was not found")
        if model.revision != expected_revision:
            logger.warning("user_profile_write_rejected operation=update outcome=stale_revision")
            raise ConflictError("Current profile revision is stale")

        values = self._values(
            scope,
            profile,
            revision=model.revision + 1,
            created_at=_utc(model.created_at),
            updated_at=_now(),
            expires_at=expires_at,
            profile_id=model.profile_id,
        )
        try:
            self._replace(model, values)
            self._session.flush()
            snapshot = self._to_snapshot(model)
            self._session.commit()
        except SQLAlchemyError as exc:
            self._rollback("update", exc)
            raise
        logger.info("user_profile_write_complete operation=update revision=%d", snapshot.revision)
        return snapshot

    def save_current(self, scope: ProfileScope, profile: UserProfile, *, expires_at: datetime) -> UserProfileSnapshot:
        """Create or replace the current completed profile atomically for this session."""

        logger.debug("user_profile_write_start operation=save_current")
        model = self._find(scope)
        now = _now()
        try:
            if model is None or _utc(model.expires_at) <= now:
                values = self._values(scope, profile, revision=1, created_at=now, updated_at=now, expires_at=expires_at)
                if model is None:
                    model = UserProfileModel(**values)
                    self._session.add(model)
                else:
                    self._replace(model, values)
            else:
                values = self._values(
                    scope,
                    profile,
                    revision=model.revision + 1,
                    created_at=_utc(model.created_at),
                    updated_at=now,
                    expires_at=expires_at,
                    profile_id=model.profile_id,
                )
                self._replace(model, values)
            self._session.flush()
            snapshot = self._to_snapshot(model)
            self._session.commit()
        except IntegrityError as exc:
            self._rollback("save_current", exc)
            raise ConflictError("Current profile could not be saved") from exc
        except SQLAlchemyError as exc:
            self._rollback("save_current", exc)
            raise
        logger.info("user_profile_write_complete operation=save_current revision=%d", snapshot.revision)
        return snapshot

    def bind_anonymous_to_account(self, scope: ProfileScope, account_id: AccountId) -> ProfileBindingOutcome:
        """Transfer an active anonymous row without merging it into an account row."""

        if scope.account_id is not None:
            logger.warning("user_profile_binding_rejected outcome=non_anonymous_scope")
            return ProfileBindingOutcome.NO_ANONYMOUS_PROFILE
        anonymous = self._session.scalar(
            select(UserProfileModel)
            .where(
                UserProfileModel.account_id.is_(None),
                UserProfileModel.session_key_hash == scope.session_key_hash,
            )
            .with_for_update()
        )
        account_profile = self._session.scalar(
            select(UserProfileModel)
            .where(UserProfileModel.account_id == account_id)
            .with_for_update()
        )
        now = _now()
        if account_profile is not None and _utc(account_profile.expires_at) > now:
            logger.info("user_profile_binding_complete outcome=account_profile_kept")
            return ProfileBindingOutcome.ACCOUNT_PROFILE_KEPT
        if anonymous is None or _utc(anonymous.expires_at) <= now:
            logger.info("user_profile_binding_complete outcome=no_anonymous_profile")
            return ProfileBindingOutcome.NO_ANONYMOUS_PROFILE
        try:
            if account_profile is not None:
                self._session.delete(account_profile)
                self._session.flush()
            anonymous.account_id = account_id
            anonymous.session_key_hash = None
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            logger.info("user_profile_binding_complete outcome=account_profile_kept")
            return ProfileBindingOutcome.ACCOUNT_PROFILE_KEPT
        except SQLAlchemyError:
            self._session.rollback()
            logger.error("user_profile_binding_failed outcome=storage_error")
            raise
        logger.info("user_profile_binding_complete outcome=bound")
        return ProfileBindingOutcome.BOUND

    @property
    def _dialect(self) -> str:
        return self._session.get_bind().dialect.name

    def _find(self, scope: ProfileScope) -> UserProfileModel | None:
        statement = select(UserProfileModel)
        if scope.account_id is not None:
            statement = statement.where(UserProfileModel.account_id == scope.account_id)
        else:
            statement = statement.where(
                UserProfileModel.account_id.is_(None),
                UserProfileModel.session_key_hash == scope.session_key_hash,
            )
        return self._session.scalar(statement)

    def _active_model(self, scope: ProfileScope) -> UserProfileModel | None:
        model = self._find(scope)
        return model if model is not None and _utc(model.expires_at) > _now() else None

    @staticmethod
    def _values(
        scope: ProfileScope,
        profile: UserProfile,
        *,
        revision: int,
        created_at: datetime,
        updated_at: datetime,
        expires_at: datetime,
        profile_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "profile_id": profile_id or "profile:" + uuid4().hex,
            "session_key_hash": scope.session_key_hash if scope.account_id is None else None,
            "account_id": scope.account_id,
            "profile_json": profile.model_dump(mode="json"),
            "revision": revision,
            "created_at": _utc(created_at),
            "updated_at": _utc(updated_at),
            "expires_at": _utc(expires_at),
        }

    @staticmethod
    def _replace(model: UserProfileModel, values: dict[str, object]) -> None:
        for field, value in values.items():
            setattr(model, field, value)

    @staticmethod
    def _to_snapshot(model: UserProfileModel) -> UserProfileSnapshot:
        try:
            profile = UserProfile.model_validate(model.profile_json, strict=False)
            return UserProfileSnapshot(
                profile_id=model.profile_id,
                profile=profile,
                revision=model.revision,
                created_at=_utc(model.created_at),
                updated_at=_utc(model.updated_at),
                expires_at=_utc(model.expires_at),
            )
        except (TypeError, ValueError) as exc:
            logger.exception("user_profile_contract_error outcome=invalid_persisted_profile")
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Persisted user profile is invalid") from exc

    def _rollback(self, operation: str, exc: SQLAlchemyError) -> None:
        self._session.rollback()
        logger.exception("user_profile_transaction_error operation=%s dialect=%s", operation, self._dialect, exc_info=exc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = ["SqlAlchemyUserProfileRepository"]
