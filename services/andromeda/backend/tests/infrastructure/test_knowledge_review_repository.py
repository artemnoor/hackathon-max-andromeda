from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.base import Base, create_engine_for_url
from andromeda.infrastructure.database.models import AccountModel
from andromeda.infrastructure.repositories.knowledge_review import (
    SqlAlchemyKnowledgeReviewActionRepository,
)
from andromeda.modules.knowledge.contracts.review import (
    KnowledgeReviewAction,
    KnowledgeReviewActionEvent,
    KnowledgeReviewCapability,
    KnowledgeReviewTargetKind,
    KnowledgeReviewTargetRef,
    knowledge_review_action_event_id,
)
from andromeda.shared.contracts.errors import ConflictError

NOW = datetime(2027, 12, 15, 12, tzinfo=UTC)
ACCOUNT_ID = "account:" + "a" * 32
IDEMPOTENCY_KEY = "review-idempotency:" + "b" * 64
TARGET = KnowledgeReviewTargetRef(
    kind=KnowledgeReviewTargetKind.CLAIM,
    object_id="claim:" + "c" * 64,
    revision=1,
    revision_hash="d" * 64,
)


def _event(*, reason: str = "Verified the cited passage against the captured source.") -> KnowledgeReviewActionEvent:
    result = KnowledgeReviewTargetRef(
        kind=TARGET.kind,
        object_id=TARGET.object_id,
        revision=2,
        revision_hash="e" * 64,
    )
    fingerprint = "f" * 64
    capability = KnowledgeReviewCapability.REVIEW_CANDIDATE
    event_id = knowledge_review_action_event_id(
        idempotency_key=IDEMPOTENCY_KEY,
        request_fingerprint=fingerprint,
        target=TARGET,
        action=KnowledgeReviewAction.APPROVE,
        result=result,
        related_target=None,
        actor_account_id=ACCOUNT_ID,
        capability=capability,
        reason=reason,
        recorded_at=NOW,
    )
    return KnowledgeReviewActionEvent(
        event_id=event_id,
        idempotency_key=IDEMPOTENCY_KEY,
        request_fingerprint=fingerprint,
        target=TARGET,
        action=KnowledgeReviewAction.APPROVE,
        result=result,
        actor_account_id=ACCOUNT_ID,
        capability=capability,
        reason=reason,
        recorded_at=NOW,
    )


def _repository_session() -> tuple[Session, Engine]:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        AccountModel(
            account_id=ACCOUNT_ID,
            email="knowledge-review@example.test",
            password_hash="test-hash",
            created_at=NOW - timedelta(days=1),
            updated_at=NOW - timedelta(days=1),
        )
    )
    session.flush()
    return session, engine


def test_review_action_repository_persists_exact_event_and_history() -> None:
    session, engine = _repository_session()
    try:
        repository = SqlAlchemyKnowledgeReviewActionRepository(session)
        event = _event()

        persisted = repository.append_action(event)

        assert persisted == event
        assert repository.get_action_by_idempotency_key(ACCOUNT_ID, IDEMPOTENCY_KEY) == event
        assert repository.list_actions(TARGET) == (event,)
    finally:
        session.close()
        engine.dispose()


def test_review_action_repository_replays_exact_insert_but_rejects_key_reuse() -> None:
    session, engine = _repository_session()
    try:
        repository = SqlAlchemyKnowledgeReviewActionRepository(session)
        original = _event()

        assert repository.append_action(original) == original
        assert repository.append_action(original) == original
        with pytest.raises(ConflictError, match="idempotency key conflicts"):
            repository.append_action(
                _event(reason="A different reason cannot reuse this actor key.")
            )
    finally:
        session.close()
        engine.dispose()
