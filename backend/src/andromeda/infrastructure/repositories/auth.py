"""SQLAlchemy adapter for account identity and opaque server-side sessions."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from andromeda.modules.auth.domain.entities import Account
from andromeda.modules.auth.repository.ports import AccountRepository
from andromeda.shared.contracts.errors import ConflictError
from andromeda.shared.contracts.ids import AccountId, SessionTokenHash

from ..database.models import AccountModel, AuthSessionModel


logger = logging.getLogger("andromeda.infrastructure.repositories.auth")


class SqlAlchemyAccountRepository(AccountRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_email(self, email: str) -> Account | None:
        model = self._session.scalar(select(AccountModel).where(AccountModel.email == email))
        return _to_account(model) if model is not None else None

    def get_credentials(self, email: str) -> tuple[Account, str] | None:
        model = self._session.scalar(select(AccountModel).where(AccountModel.email == email))
        return (_to_account(model), model.password_hash) if model is not None else None

    def get_by_id(self, account_id: AccountId) -> Account | None:
        model = self._session.get(AccountModel, account_id)
        return _to_account(model) if model is not None else None

    def create(self, account_id: AccountId, email: str, password_hash: str, *, now: datetime) -> Account:
        model = AccountModel(
            account_id=account_id,
            email=email,
            password_hash=password_hash,
            created_at=_utc(now),
            updated_at=_utc(now),
        )
        try:
            self._session.add(model)
            self._session.flush()
            account = _to_account(model)
            self._session.commit()
            return account
        except IntegrityError as exc:
            self._session.rollback()
            logger.info("auth_repository_write_rejected operation=create outcome=conflict")
            raise ConflictError("Account already exists") from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.error("auth_repository_write_failed operation=create")
            raise RuntimeError("Account persistence failed") from exc

    def create_session(self, account_id: AccountId, token_hash: SessionTokenHash, *, now: datetime, expires_at: datetime) -> None:
        model = AuthSessionModel(
            session_id="session:" + uuid4().hex,
            account_id=account_id,
            token_hash=token_hash,
            created_at=_utc(now),
            expires_at=_utc(expires_at),
        )
        try:
            self._session.add(model)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            logger.info("auth_repository_write_rejected operation=create_session outcome=conflict")
            raise ConflictError("Session could not be created") from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.error("auth_repository_write_failed operation=create_session")
            raise RuntimeError("Session persistence failed") from exc

    def get_by_session_hash(self, token_hash: SessionTokenHash, *, now: datetime) -> Account | None:
        model = self._session.scalar(
            select(AccountModel)
            .join(AuthSessionModel, AuthSessionModel.account_id == AccountModel.account_id)
            .where(
                AuthSessionModel.token_hash == token_hash,
                AuthSessionModel.revoked_at.is_(None),
                AuthSessionModel.expires_at > _utc(now),
            )
        )
        return _to_account(model) if model is not None else None

    def purge_expired_sessions(self, *, now: datetime) -> int:
        try:
            result = self._session.execute(delete(AuthSessionModel).where(AuthSessionModel.expires_at <= _utc(now)))
            self._session.commit()
            deleted = int(getattr(result, "rowcount", 0) or 0)
            if deleted:
                logger.info("auth_expired_sessions_purged count=%d", deleted)
            return deleted
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.error("auth_repository_write_failed operation=purge_expired_sessions")
            raise RuntimeError("Expired session cleanup failed") from exc

    def revoke_session(self, token_hash: SessionTokenHash, *, now: datetime) -> None:
        model = self._session.scalar(select(AuthSessionModel).where(AuthSessionModel.token_hash == token_hash))
        if model is None or model.revoked_at is not None:
            return
        model.revoked_at = _utc(now)
        try:
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.error("auth_repository_write_failed operation=revoke_session")
            raise RuntimeError("Session revocation failed") from exc


def _to_account(model: AccountModel) -> Account:
    return Account(accountId=model.account_id, email=model.email, createdAt=_utc(model.created_at))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = ["SqlAlchemyAccountRepository"]
