"""Persistence adapter for immutable knowledge-review action audit."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import KnowledgeReviewActionModel
from andromeda.modules.knowledge.contracts.review import (
    KnowledgeReviewAction,
    KnowledgeReviewActionEvent,
    KnowledgeReviewCapability,
    KnowledgeReviewTargetKind,
    KnowledgeReviewTargetRef,
    ReviewIdempotencyKey,
)
from andromeda.modules.knowledge.repository.ports import KnowledgeReviewActionRepository
from andromeda.shared.contracts.errors import ConflictError, ValidationError

logger = logging.getLogger("andromeda.infrastructure.repositories.knowledge_review")


class SqlAlchemyKnowledgeReviewActionRepository(KnowledgeReviewActionRepository):
    """Append-only event ledger; transaction lifecycle belongs to the caller."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_action_by_idempotency_key(
        self,
        actor_account_id: str,
        idempotency_key: ReviewIdempotencyKey,
    ) -> KnowledgeReviewActionEvent | None:
        row = self._session.scalar(
            select(KnowledgeReviewActionModel).where(
                KnowledgeReviewActionModel.actor_account_id == actor_account_id,
                KnowledgeReviewActionModel.idempotency_key == idempotency_key,
            )
        )
        return _to_event(row) if row is not None else None

    def append_action(self, event: KnowledgeReviewActionEvent) -> KnowledgeReviewActionEvent:
        values = _model_values(event)
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "postgresql":
            self._session.execute(
                postgresql_insert(KnowledgeReviewActionModel)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["actor_account_id", "idempotency_key"]
                )
            )
        elif dialect_name == "sqlite":
            self._session.execute(
                sqlite_insert(KnowledgeReviewActionModel)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["actor_account_id", "idempotency_key"]
                )
            )
        else:
            stored_model = self._session.get(KnowledgeReviewActionModel, event.event_id)
            if stored_model is None:
                self._session.add(KnowledgeReviewActionModel(**values))
                self._session.flush()

        persisted_action = self.get_action_by_idempotency_key(
            event.actor_account_id,
            event.idempotency_key,
        )
        if persisted_action is None:
            raise ConflictError("Knowledge review action insert was not persisted")
        if persisted_action != event:
            raise ConflictError("Knowledge review idempotency key conflicts with another action")
        logger.info(
            "knowledge_review_action_persisted event_id=%s target_kind=%s action=%s",
            persisted_action.event_id,
            persisted_action.target.kind.value,
            persisted_action.action.value,
        )
        return persisted_action

    def list_actions(
        self,
        target: KnowledgeReviewTargetRef,
        *,
        limit: int = 100,
    ) -> tuple[KnowledgeReviewActionEvent, ...]:
        if not 1 <= limit <= 500:
            raise ValidationError("knowledge review history query cap must be within 1..500")
        rows = self._session.scalars(
            select(KnowledgeReviewActionModel)
            .where(
                KnowledgeReviewActionModel.target_kind == target.kind.value,
                KnowledgeReviewActionModel.target_id == target.object_id,
            )
            .order_by(
                KnowledgeReviewActionModel.recorded_at,
                KnowledgeReviewActionModel.event_id,
            )
            .limit(limit)
        )
        return tuple(_to_event(row) for row in rows)


def _model_values(event: KnowledgeReviewActionEvent) -> dict[str, object | None]:
    return {
        "event_id": event.event_id,
        "idempotency_key": event.idempotency_key,
        "request_fingerprint": event.request_fingerprint,
        "target_kind": event.target.kind.value,
        "target_id": event.target.object_id,
        "target_revision": event.target.revision,
        "target_hash": event.target.revision_hash,
        "action": event.action.value,
        "result_id": event.result.object_id,
        "result_revision": event.result.revision,
        "result_hash": event.result.revision_hash,
        "related_kind": event.related_target.kind.value if event.related_target else None,
        "related_id": event.related_target.object_id if event.related_target else None,
        "related_revision": event.related_target.revision if event.related_target else None,
        "related_hash": event.related_target.revision_hash if event.related_target else None,
        "actor_account_id": event.actor_account_id,
        "capability": event.capability.value,
        "reason": event.reason,
        "recorded_at": event.recorded_at,
    }


def _to_event(row: KnowledgeReviewActionModel) -> KnowledgeReviewActionEvent:
    target_kind = KnowledgeReviewTargetKind(row.target_kind)
    target = KnowledgeReviewTargetRef(
        kind=target_kind,
        object_id=row.target_id,
        revision=row.target_revision,
        revision_hash=row.target_hash,
    )
    result = KnowledgeReviewTargetRef(
        kind=target_kind,
        object_id=row.result_id,
        revision=row.result_revision,
        revision_hash=row.result_hash,
    )
    related = None
    if row.related_kind is not None:
        if (
            row.related_id is None
            or row.related_revision is None
            or row.related_hash is None
        ):
            raise ConflictError("Persisted knowledge review action has incomplete related target")
        related = KnowledgeReviewTargetRef(
            kind=KnowledgeReviewTargetKind(row.related_kind),
            object_id=row.related_id,
            revision=row.related_revision,
            revision_hash=row.related_hash,
        )
    return KnowledgeReviewActionEvent(
        event_id=row.event_id,
        idempotency_key=row.idempotency_key,
        request_fingerprint=row.request_fingerprint,
        target=target,
        action=KnowledgeReviewAction(row.action),
        result=result,
        related_target=related,
        actor_account_id=row.actor_account_id,
        capability=KnowledgeReviewCapability(row.capability),
        reason=row.reason,
        recorded_at=_utc(row.recorded_at),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SqlAlchemyKnowledgeReviewActionRepository"]
