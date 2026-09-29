from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import KnowledgeManualSubmissionModel
from andromeda.modules.knowledge.contracts.public import (
    KnowledgeManualSubmission,
    ManualSubmissionKind,
)
from andromeda.modules.knowledge.repository.ports import (
    KnowledgeManualSubmissionRepository,
)
from andromeda.shared.contracts.errors import ConflictError


class SqlAlchemyKnowledgeManualSubmissionRepository(KnowledgeManualSubmissionRepository):
    """Append-only persistence adapter for manual submission attribution."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_idempotency_key(
        self, actor_account_id: str, idempotency_key: str
    ) -> KnowledgeManualSubmission | None:
        row = self._session.scalar(
            select(KnowledgeManualSubmissionModel).where(
                KnowledgeManualSubmissionModel.actor_account_id == actor_account_id,
                KnowledgeManualSubmissionModel.idempotency_key == idempotency_key,
            )
        )
        return _to_contract(row) if row is not None else None

    def get_latest_for_target(
        self, target_id: str
    ) -> KnowledgeManualSubmission | None:
        row = self._session.scalar(
            select(KnowledgeManualSubmissionModel)
            .where(KnowledgeManualSubmissionModel.target_id == target_id)
            .order_by(
                KnowledgeManualSubmissionModel.target_revision.desc(),
                KnowledgeManualSubmissionModel.recorded_at.desc(),
            )
            .limit(1)
        )
        return _to_contract(row) if row is not None else None

    def append_submission(
        self, submission: KnowledgeManualSubmission
    ) -> KnowledgeManualSubmission:
        existing = self.get_by_idempotency_key(
            submission.actor_account_id, submission.idempotency_key
        )
        if existing is not None:
            if existing != submission:
                raise ConflictError("Manual submission idempotency key was already used")
            return existing
        row = self._session.get(KnowledgeManualSubmissionModel, submission.submission_id)
        if row is not None:
            persisted = _to_contract(row)
            if persisted != submission:
                raise ConflictError("Manual submission identities are immutable")
            return persisted
        self._session.add(
            KnowledgeManualSubmissionModel(
                submission_id=submission.submission_id,
                kind=submission.kind.value,
                idempotency_key=submission.idempotency_key,
                request_fingerprint=submission.request_fingerprint,
                actor_account_id=submission.actor_account_id,
                university_id=submission.university_id,
                reason=str(submission.reason),
                target_id=submission.target_id,
                target_revision=submission.target_revision,
                target_hash=submission.target_hash,
                source_observation_id=submission.source_observation_id,
                expires_at=_utc(submission.expires_at),
                recorded_at=_utc(submission.recorded_at),
            )
        )
        self._session.flush()
        return submission


def _to_contract(row: KnowledgeManualSubmissionModel) -> KnowledgeManualSubmission:
    return KnowledgeManualSubmission(
        submission_id=row.submission_id,
        kind=ManualSubmissionKind(row.kind),
        idempotency_key=row.idempotency_key,
        request_fingerprint=row.request_fingerprint,
        actor_account_id=row.actor_account_id,
        university_id=row.university_id,
        reason=row.reason,
        target_id=row.target_id,
        target_revision=row.target_revision,
        target_hash=row.target_hash,
        source_observation_id=row.source_observation_id,
        expires_at=_aware(row.expires_at) if row.expires_at is not None else None,
        recorded_at=_aware(row.recorded_at),
    )


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(UTC) if value is not None else None


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SqlAlchemyKnowledgeManualSubmissionRepository"]
