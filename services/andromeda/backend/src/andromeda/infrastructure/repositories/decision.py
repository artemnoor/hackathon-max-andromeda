"""SQLAlchemy adapter for owner-bound DecisionContext state."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from andromeda.modules.decision.domain.entities import DecisionSnapshot, DecisionState
from andromeda.modules.decision.repository.ports import DecisionBindingOutcome, DecisionContextRepository
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.shared.contracts.errors import ConflictError, ContractError, ErrorCode, NotFoundError
from andromeda.shared.contracts.ids import AccountId

from ..database.models import DecisionContextModel


logger = logging.getLogger("andromeda.infrastructure.repositories.decision")


class SqlAlchemyDecisionContextRepository(DecisionContextRepository):
    """Persist one current explicit decision state per anonymous/account owner."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_current(self, scope: ProfileScope) -> DecisionSnapshot | None:
        logger.debug("decision_context_read_start operation=get_current dialect=%s owner_kind=%s", self._dialect, scope.owner_kind)
        model = self._find(scope)
        if model is None:
            logger.debug("decision_context_read_complete outcome=missing")
            return None
        if _utc(model.expires_at) <= _now():
            logger.warning("decision_context_read_empty outcome=expired owner_kind=%s", scope.owner_kind)
            return None
        snapshot = self._to_snapshot(model)
        logger.debug("decision_context_read_complete outcome=found revision=%d", snapshot.revision)
        return snapshot

    def get_or_create(self, scope: ProfileScope, *, expires_at: datetime) -> DecisionSnapshot:
        """Read an active state or create a blank one without implicit choices."""

        logger.debug("decision_context_write_start operation=get_or_create owner_kind=%s", scope.owner_kind)
        existing = self._find(scope, for_update=True)
        now = _now()
        if existing is not None and _utc(existing.expires_at) > now:
            snapshot = self._to_snapshot(existing)
            self._session.commit()
            logger.debug("decision_context_write_complete operation=get_or_create outcome=existing revision=%d", snapshot.revision)
            return snapshot

        state = DecisionState(created_at=now, updated_at=now)
        values = self._values(scope, state, expires_at=expires_at)
        try:
            if existing is None:
                model = DecisionContextModel(**values)
                self._session.add(model)
            else:
                model = existing
                self._replace(model, values)
            self._session.flush()
            snapshot = self._to_snapshot(model)
            self._session.commit()
        except IntegrityError as exc:
            self._rollback("get_or_create", exc)
            concurrent = self._find(scope)
            if concurrent is not None and _utc(concurrent.expires_at) > _now():
                snapshot = self._to_snapshot(concurrent)
                logger.info("decision_context_write_complete operation=get_or_create outcome=concurrent_existing revision=%d", snapshot.revision)
                return snapshot
            raise ConflictError("Decision context already exists") from exc
        except SQLAlchemyError as exc:
            self._rollback("get_or_create", exc)
            raise
        logger.info("decision_context_write_complete operation=get_or_create outcome=created revision=%d", snapshot.revision)
        return snapshot

    def save(
        self,
        scope: ProfileScope,
        state: DecisionState,
        *,
        expected_revision: int,
        expires_at: datetime,
    ) -> DecisionSnapshot:
        """Save one explicit transition with optimistic revision checking."""

        logger.debug(
            "decision_context_write_start operation=save owner_kind=%s expected_revision=%d shortlist_count=%d",
            scope.owner_kind,
            expected_revision,
            len(state.choice.active_shortlist),
        )
        if expected_revision < 1:
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Decision context expected revision must be positive")
        if state.revision != expected_revision + 1:
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Decision state revision must be the next revision")
        model = self._find(scope, for_update=True)
        if model is None or _utc(model.expires_at) <= _now():
            self._session.rollback()
            raise NotFoundError("Current decision context was not found")
        if model.revision != expected_revision:
            self._session.rollback()
            logger.warning("decision_context_write_rejected operation=save outcome=stale_revision")
            raise ConflictError("Current decision context revision is stale")
        values = self._values(scope, state, expires_at=expires_at, decision_id=model.decision_id)
        try:
            self._replace(model, values)
            self._session.flush()
            snapshot = self._to_snapshot(model)
            self._session.commit()
        except SQLAlchemyError as exc:
            self._rollback("save", exc)
            raise
        logger.info("decision_context_write_complete operation=save revision=%d shortlist_count=%d", snapshot.revision, len(state.choice.active_shortlist))
        return snapshot

    def bind_anonymous_to_account(self, scope: ProfileScope, account_id: AccountId) -> DecisionBindingOutcome:
        """Transfer only anonymous state when the account has no active state."""

        if scope.account_id is not None:
            logger.warning("decision_context_binding_rejected outcome=non_anonymous_scope")
            return DecisionBindingOutcome.NO_ANONYMOUS_STATE
        logger.debug("decision_context_binding_start owner_kind=anonymous")
        anonymous = self._session.scalar(
            select(DecisionContextModel)
            .where(
                DecisionContextModel.account_id.is_(None),
                DecisionContextModel.session_key_hash == scope.session_key_hash,
            )
            .with_for_update()
        )
        account_context = self._session.scalar(
            select(DecisionContextModel)
            .where(DecisionContextModel.account_id == account_id)
            .with_for_update()
        )
        now = _now()
        if account_context is not None and _utc(account_context.expires_at) > now:
            self._session.commit()
            logger.info("decision_context_binding_complete outcome=account_state_kept")
            return DecisionBindingOutcome.ACCOUNT_STATE_KEPT
        if anonymous is None or _utc(anonymous.expires_at) <= now:
            self._session.commit()
            logger.info("decision_context_binding_complete outcome=no_anonymous_state")
            return DecisionBindingOutcome.NO_ANONYMOUS_STATE
        try:
            if account_context is not None:
                self._session.delete(account_context)
                self._session.flush()
            anonymous.account_id = account_id
            anonymous.session_key_hash = None
            anonymous.owner_key = f"account:{account_id.removeprefix('account:')}"
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            logger.info("decision_context_binding_complete outcome=account_state_kept")
            return DecisionBindingOutcome.ACCOUNT_STATE_KEPT
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("decision_context_binding_failed outcome=storage_error", exc_info=exc)
            raise
        logger.info("decision_context_binding_complete outcome=bound")
        return DecisionBindingOutcome.BOUND

    def replace_account_with_anonymous(self, scope: ProfileScope, account_id: AccountId) -> DecisionBindingOutcome:
        """Explicitly import the guest decision state after a conflict.

        This operation is never called by login itself. It is a separate
        user-confirmed command, so an existing account choice cannot be
        silently overwritten.
        """

        if scope.account_id is not None:
            return DecisionBindingOutcome.NO_ANONYMOUS_STATE
        anonymous = self._session.scalar(
            select(DecisionContextModel)
            .where(
                DecisionContextModel.account_id.is_(None),
                DecisionContextModel.session_key_hash == scope.session_key_hash,
            )
            .with_for_update()
        )
        account_context = self._session.scalar(
            select(DecisionContextModel)
            .where(DecisionContextModel.account_id == account_id)
            .with_for_update()
        )
        if anonymous is None or _utc(anonymous.expires_at) <= _now():
            self._session.commit()
            return DecisionBindingOutcome.NO_ANONYMOUS_STATE
        try:
            if account_context is not None:
                self._session.delete(account_context)
                self._session.flush()
            anonymous.account_id = account_id
            anonymous.session_key_hash = None
            anonymous.owner_key = f"account:{account_id.removeprefix('account:')}"
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise
        logger.info("decision_context_binding_complete outcome=explicit_guest_import")
        return DecisionBindingOutcome.BOUND

    @property
    def _dialect(self) -> str:
        return self._session.get_bind().dialect.name

    def _find(self, scope: ProfileScope, *, for_update: bool = False) -> DecisionContextModel | None:
        statement = select(DecisionContextModel)
        if scope.account_id is not None:
            statement = statement.where(DecisionContextModel.account_id == scope.account_id)
        else:
            statement = statement.where(
                DecisionContextModel.account_id.is_(None),
                DecisionContextModel.session_key_hash == scope.session_key_hash,
            )
        if for_update:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    @staticmethod
    def _values(
        scope: ProfileScope,
        state: DecisionState,
        *,
        expires_at: datetime,
        decision_id: str | None = None,
    ) -> dict[str, object]:
        expires = _utc(expires_at)
        updated = _utc(state.updated_at)
        if expires <= updated:
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Decision context expiry must be after updated_at")
        return {
            "decision_id": decision_id or "decision:" + uuid4().hex,
            "owner_key": scope.owner_key,
            "session_key_hash": scope.session_key_hash if scope.account_id is None else None,
            "account_id": scope.account_id,
            "state_json": state.model_dump(mode="json"),
            "revision": state.revision,
            "created_at": _utc(state.created_at),
            "updated_at": updated,
            "expires_at": expires,
        }

    @staticmethod
    def _replace(model: DecisionContextModel, values: dict[str, object]) -> None:
        for field, value in values.items():
            setattr(model, field, value)

    @staticmethod
    def _to_snapshot(model: DecisionContextModel) -> DecisionSnapshot:
        try:
            state = DecisionState.model_validate(model.state_json, strict=False)
            return DecisionSnapshot(
                decision_id=model.decision_id,
                owner_key=model.owner_key,
                state=state,
                revision=model.revision,
                created_at=_utc(model.created_at),
                updated_at=_utc(model.updated_at),
                expires_at=_utc(model.expires_at),
            )
        except (TypeError, ValueError) as exc:
            logger.exception("decision_context_contract_error outcome=invalid_persisted_state")
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Persisted decision context is invalid") from exc

    def _rollback(self, operation: str, exc: SQLAlchemyError) -> None:
        self._session.rollback()
        logger.exception("decision_context_transaction_error operation=%s dialect=%s", operation, self._dialect, exc_info=exc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = ["SqlAlchemyDecisionContextRepository"]
