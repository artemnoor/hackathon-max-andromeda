"""Owner-bound SQLAlchemy persistence for generic QuerySession state."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from andromeda.modules.conversation.contracts.public import QuerySession, QuerySessionId
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.shared.contracts.errors import (
    ConflictError,
    ContractError,
    ErrorCode,
    NotFoundError,
)

from ..database.models import QuerySessionModel

logger = logging.getLogger("andromeda.infrastructure.repositories.query_sessions")


class SqlAlchemyQuerySessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, session_id: QuerySessionId, *, owner_scope: ProfileScope) -> QuerySession | None:
        model = self._session.scalar(
            select(QuerySessionModel).where(
                QuerySessionModel.session_id == session_id,
                QuerySessionModel.owner_key == owner_scope.owner_key,
            )
        )
        if model is None:
            return None
        if _utc(model.expires_at) <= _now():
            logger.info("query_session_read outcome=expired")
            return None
        return _to_contract(model, owner_scope)

    def save(self, session: QuerySession, *, expected_revision: int | None = None) -> QuerySession:
        owner_scope = session.owner_scope
        model = self._session.scalar(
            select(QuerySessionModel)
            .where(
                QuerySessionModel.session_id == session.session_id,
                QuerySessionModel.owner_key == owner_scope.owner_key,
            )
            .with_for_update()
        )
        if model is None:
            if expected_revision is not None:
                raise ConflictError("query session owner or revision was not found")
            self._session.add(QuerySessionModel(**_model_values(session)))
            try:
                self._session.commit()
            except IntegrityError as exc:
                self._session.rollback()
                raise ConflictError("query session already exists") from exc
            return session
        if expected_revision is not None and model.revision != expected_revision:
            self._session.rollback()
            raise ConflictError("query session revision is stale")
        if session.revision <= model.revision:
            self._session.rollback()
            raise ConflictError("query session revision must advance")
        values = _model_values(session)
        for key, value in values.items():
            setattr(model, key, value)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("query session update conflicted") from exc
        return session

    def purge_expired(self, *, now: datetime | None = None, limit: int = 500) -> int:
        if limit < 1 or limit > 5000:
            raise ValueError("query session purge limit must be between 1 and 5000")
        cutoff = now or _now()
        expired_ids = tuple(
            self._session.scalars(
                select(QuerySessionModel.session_id)
                .where(QuerySessionModel.expires_at <= cutoff)
                .order_by(QuerySessionModel.expires_at, QuerySessionModel.session_id)
                .limit(limit)
            ).all()
        )
        if not expired_ids:
            return 0
        result = self._session.execute(delete(QuerySessionModel).where(QuerySessionModel.session_id.in_(expired_ids)))
        self._session.commit()
        deleted = int(getattr(result, "rowcount", 0) or 0)
        logger.info("query_session_purge outcome=completed count=%s", deleted)
        return deleted

    def bind_anonymous_to_account(self, session_id: QuerySessionId, *, anonymous_scope: ProfileScope, account_id: str) -> QuerySession:
        if anonymous_scope.account_id is not None:
            raise ContractError(ErrorCode.INVALID_QUERY, "anonymous scope is required for query session binding")
        model = self._session.scalar(
            select(QuerySessionModel)
            .where(
                QuerySessionModel.session_id == session_id,
                QuerySessionModel.owner_key == anonymous_scope.owner_key,
            )
            .with_for_update()
        )
        if model is None:
            raise NotFoundError("query session was not found for anonymous owner")
        session = _to_contract(model, anonymous_scope)
        account_scope = ProfileScope(session_key_hash=anonymous_scope.session_key_hash, account_id=account_id)
        model.owner_key = account_scope.owner_key
        model.session_key_hash = None
        model.account_id = account_id
        session = session.model_copy(update={"owner_scope": account_scope})
        model.state_json = session.model_dump(mode="json")
        self._session.commit()
        return session


def _model_values(session: QuerySession) -> dict[str, object]:
    scope = session.owner_scope
    return {
        "session_id": session.session_id,
        "owner_key": scope.owner_key,
        "session_key_hash": scope.session_key_hash if scope.account_id is None else None,
        "account_id": scope.account_id,
        "state_json": session.model_dump(mode="json"),
        "revision": session.revision,
        "created_at": _utc(session.created_at),
        "updated_at": _utc(session.updated_at),
        "expires_at": _utc(session.expires_at),
    }


def _to_contract(model: QuerySessionModel, owner_scope: ProfileScope) -> QuerySession:
    try:
        state = model.state_json if isinstance(model.state_json, dict) else {}
        session = QuerySession.model_validate(state, strict=False)
        if session.owner_scope.owner_key != model.owner_key:
            raise ValueError("persisted query session owner mismatch")
        return session.model_copy(update={"owner_scope": owner_scope})
    except (TypeError, ValueError) as exc:
        logger.exception("query_session_contract_error outcome=invalid_persisted_state")
        raise ContractError(ErrorCode.CONTRACT_ERROR, "Persisted query session is invalid") from exc


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SqlAlchemyQuerySessionRepository"]
