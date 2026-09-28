"""SQLAlchemy adapter for idempotent policy projection refresh tracking."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    PolicyProjectionRefreshAttemptModel,
    PolicyProjectionRefreshModel,
)
from andromeda.modules.policy.contracts.applicability import PolicySelection
from andromeda.modules.policy.contracts.dependencies import (
    PolicyDependencyNode,
    PolicyDependencyNodeKind,
)
from andromeda.modules.policy.contracts.refresh import (
    PolicyProjectionKind,
    PolicyProjectionRefreshAttempt,
    PolicyProjectionRefreshCommand,
    PolicyProjectionRefreshKey,
    PolicyProjectionRefreshOutcome,
    PolicyProjectionRefreshRecord,
    PolicyProjectionRefreshState,
    policy_projection_invalidation_fingerprint,
    policy_projection_refresh_attempt_id,
    policy_projection_refresh_key,
)
from andromeda.modules.policy.contracts.rule import PolicyDomainOwner
from andromeda.shared.contracts.errors import NotFoundError, ValidationError
from andromeda.shared.contracts.ids import SourceHash

logger = logging.getLogger("andromeda.infrastructure.repositories.policy_refresh")

_FAILURE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class SqlAlchemyPolicyProjectionRefreshRepository:
    """Append-only refresh attempt history with generation-checked state updates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def mark_dirty(self, command: PolicyProjectionRefreshCommand) -> PolicyProjectionRefreshRecord:
        refresh_key = policy_projection_refresh_key(command.projection_kind, command.target)
        fingerprint = policy_projection_invalidation_fingerprint(command)
        updated_at = _utc(command.invalidated_at)
        initial = {
            "refresh_key": refresh_key,
            "target_kind": command.target.kind.value,
            "target_object_id": command.target.object_id,
            "target_revision": command.target.revision,
            "target_content_hash": command.target.content_hash,
            "target_owner_module": command.target.owner_module,
            "projection_kind": command.projection_kind.value,
            "generation": 1,
            "completed_generation": 0,
            "invalidated_by_json": [item.model_dump(mode="json") for item in command.invalidated_by],
            "invalidation_fingerprint": fingerprint,
            "state": PolicyProjectionRefreshState.DIRTY.value,
            "projection_version": None,
            "attempt_count": 0,
            "last_attempt_at": None,
            "last_success_at": None,
            "last_updated_at": updated_at,
            "failure_code": None,
        }
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "postgresql":
            self._session.execute(
                postgresql_insert(PolicyProjectionRefreshModel)
                .values(**initial)
                .on_conflict_do_nothing(index_elements=["refresh_key"])
            )
        elif dialect_name == "sqlite":
            self._session.execute(
                sqlite_insert(PolicyProjectionRefreshModel)
                .values(**initial)
                .on_conflict_do_nothing(index_elements=["refresh_key"])
            )
        else:
            existing = self._session.get(PolicyProjectionRefreshModel, refresh_key)
            if existing is None:
                self._session.add(PolicyProjectionRefreshModel(**initial))
                self._session.flush()

        row = self._locked_row(refresh_key)
        if row.invalidation_fingerprint != fingerprint:
            if row.generation >= 2_147_483_647:
                raise ValidationError("policy projection refresh generation exhausted")
            row.generation += 1
            row.invalidated_by_json = [
                item.model_dump(mode="json") for item in command.invalidated_by
            ]
            row.invalidation_fingerprint = fingerprint
            row.state = PolicyProjectionRefreshState.DIRTY.value
            row.failure_code = None
            row.last_updated_at = updated_at
            self._session.flush()
        return _to_record(row)

    def get_refresh_state(
        self, refresh_key: PolicyProjectionRefreshKey
    ) -> PolicyProjectionRefreshRecord | None:
        row = self._session.get(PolicyProjectionRefreshModel, refresh_key)
        return _to_record(row) if row is not None else None

    def list_dirty(self, *, limit: int = 100) -> tuple[PolicyProjectionRefreshRecord, ...]:
        if not 1 <= limit <= 100:
            raise ValidationError("policy projection refresh query cap must be within 1..100")
        rows = self._session.scalars(
            select(PolicyProjectionRefreshModel)
            .where(PolicyProjectionRefreshModel.state.in_(
                (PolicyProjectionRefreshState.DIRTY.value, PolicyProjectionRefreshState.FAILED.value)
            ))
            .order_by(
                PolicyProjectionRefreshModel.last_updated_at,
                PolicyProjectionRefreshModel.refresh_key,
            )
            .limit(limit)
        )
        return tuple(_to_record(row) for row in rows)

    def record_success(
        self,
        refresh_key: PolicyProjectionRefreshKey,
        *,
        generation: int,
        projection_version: str,
        recorded_at: datetime,
    ) -> PolicyProjectionRefreshRecord:
        row = self._locked_row(refresh_key)
        now = _utc(recorded_at)
        version = SourceHash(projection_version)
        if row.generation != generation or row.state == PolicyProjectionRefreshState.READY.value:
            self._append_attempt(
                row,
                generation=generation,
                outcome=PolicyProjectionRefreshOutcome.STALE_RESULT_REJECTED,
                projection_version=version,
                failure_code=(
                    "generation_advanced"
                    if row.generation != generation
                    else "refresh_already_completed"
                ),
                recorded_at=now,
            )
            self._session.flush()
            return _to_record(row)
        self._append_attempt(
            row,
            generation=generation,
            outcome=PolicyProjectionRefreshOutcome.COMPLETED,
            projection_version=version,
            failure_code=None,
            recorded_at=now,
        )
        row.completed_generation = generation
        row.projection_version = version
        row.state = PolicyProjectionRefreshState.READY.value
        row.last_success_at = now
        row.failure_code = None
        row.last_updated_at = now
        self._session.flush()
        return _to_record(row)

    def record_failure(
        self,
        refresh_key: PolicyProjectionRefreshKey,
        *,
        generation: int,
        failure_code: str,
        recorded_at: datetime,
    ) -> PolicyProjectionRefreshRecord:
        if not _FAILURE_CODE_PATTERN.fullmatch(failure_code):
            raise ValidationError("policy projection refresh failure code is invalid")
        row = self._locked_row(refresh_key)
        now = _utc(recorded_at)
        self._append_attempt(
            row,
            generation=generation,
            outcome=PolicyProjectionRefreshOutcome.FAILED,
            projection_version=None,
            failure_code=failure_code,
            recorded_at=now,
        )
        if row.generation == generation and row.state != PolicyProjectionRefreshState.READY.value:
            row.state = PolicyProjectionRefreshState.FAILED.value
            row.failure_code = failure_code
            row.last_updated_at = now
        self._session.flush()
        return _to_record(row)

    def list_attempts(
        self, refresh_key: PolicyProjectionRefreshKey, *, limit: int = 100
    ) -> tuple[PolicyProjectionRefreshAttempt, ...]:
        if not 1 <= limit <= 1000:
            raise ValidationError("policy projection attempt query cap must be within 1..1000")
        rows = self._session.scalars(
            select(PolicyProjectionRefreshAttemptModel)
            .where(PolicyProjectionRefreshAttemptModel.refresh_key == refresh_key)
            .order_by(PolicyProjectionRefreshAttemptModel.sequence)
            .limit(limit)
        )
        return tuple(_to_attempt(row) for row in rows)

    def _locked_row(self, refresh_key: PolicyProjectionRefreshKey) -> PolicyProjectionRefreshModel:
        row = self._session.scalar(
            select(PolicyProjectionRefreshModel)
            .where(PolicyProjectionRefreshModel.refresh_key == refresh_key)
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("Policy projection refresh state does not exist")
        return row

    def _append_attempt(
        self,
        row: PolicyProjectionRefreshModel,
        *,
        generation: int,
        outcome: PolicyProjectionRefreshOutcome,
        projection_version: SourceHash | None,
        failure_code: str | None,
        recorded_at: datetime,
    ) -> None:
        sequence = row.attempt_count + 1
        attempt = PolicyProjectionRefreshAttempt(
            attempt_id=policy_projection_refresh_attempt_id(
                row.refresh_key,
                sequence,
                generation,
                outcome,
                projection_version,
                failure_code,
            ),
            refresh_key=row.refresh_key,
            sequence=sequence,
            generation=generation,
            outcome=outcome,
            projection_version=projection_version,
            failure_code=failure_code,
            recorded_at=recorded_at,
        )
        self._session.add(
            PolicyProjectionRefreshAttemptModel(
                attempt_id=attempt.attempt_id,
                refresh_key=attempt.refresh_key,
                sequence=attempt.sequence,
                generation=attempt.generation,
                outcome=attempt.outcome.value,
                projection_version=attempt.projection_version,
                failure_code=attempt.failure_code,
                recorded_at=attempt.recorded_at,
            )
        )
        row.attempt_count = sequence
        row.last_attempt_at = recorded_at


def _to_record(row: PolicyProjectionRefreshModel) -> PolicyProjectionRefreshRecord:
    target = PolicyDependencyNode(
        kind=PolicyDependencyNodeKind(row.target_kind),
        object_id=row.target_object_id,
        revision=row.target_revision,
        content_hash=row.target_content_hash,
        owner_module=row.target_owner_module,
    )
    invalidators = tuple(
        _selection_from_json(item) for item in row.invalidated_by_json
    )
    return PolicyProjectionRefreshRecord(
        refresh_key=row.refresh_key,
        target=target,
        projection_kind=PolicyProjectionKind(row.projection_kind),
        generation=row.generation,
        completed_generation=row.completed_generation,
        invalidated_by=invalidators,
        invalidation_fingerprint=row.invalidation_fingerprint,
        state=PolicyProjectionRefreshState(row.state),
        projection_version=row.projection_version,
        attempt_count=row.attempt_count,
        last_attempt_at=_utc_optional(row.last_attempt_at),
        last_success_at=_utc_optional(row.last_success_at),
        last_updated_at=_utc(row.last_updated_at),
        failure_code=row.failure_code,
    )


def _selection_from_json(payload: dict[str, object]) -> PolicySelection:
    restored = dict(payload)
    raw_domain = restored.get("domain_rule")
    if not isinstance(raw_domain, dict):
        raise ValidationError("persisted policy refresh invalidator has no owner reference")
    domain_payload = dict(raw_domain)
    domain_payload["owner_module"] = PolicyDomainOwner(str(domain_payload["owner_module"]))
    restored["domain_rule"] = domain_payload
    return PolicySelection.model_validate(restored)


def _to_attempt(row: PolicyProjectionRefreshAttemptModel) -> PolicyProjectionRefreshAttempt:
    return PolicyProjectionRefreshAttempt(
        attempt_id=row.attempt_id,
        refresh_key=row.refresh_key,
        sequence=row.sequence,
        generation=row.generation,
        outcome=PolicyProjectionRefreshOutcome(row.outcome),
        projection_version=row.projection_version,
        failure_code=row.failure_code,
        recorded_at=_utc(row.recorded_at),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _utc_optional(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None


__all__ = ["SqlAlchemyPolicyProjectionRefreshRepository"]
