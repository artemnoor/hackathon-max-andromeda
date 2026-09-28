"""Bounded source-discovery observations, separate from policy lifecycle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .sources import SourceId, SourceObservationId

PollAttemptId = Annotated[str, StringConstraints(pattern=r"^poll-attempt:[a-f0-9]{32}$")]


class SourcePollOutcome(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    UNAVAILABLE = "unavailable"
    REMOVED = "removed"


class SourcePollAttempt(ContractModel):
    """Immutable record of one bounded poll attempt and its observed content hash."""

    attempt_id: PollAttemptId
    source_id: SourceId
    registry_revision: int = Field(strict=True, ge=1)
    started_at: datetime
    completed_at: datetime
    outcome: SourcePollOutcome
    parser_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    previous_snapshot_sha256: SourceHash | None = None
    snapshot_sha256: SourceHash | None = None
    last_successful_snapshot_sha256: SourceHash | None = None
    source_observation_id: SourceObservationId | None = None
    retry_count: int = Field(strict=True, ge=0, le=10)
    next_retry_at: datetime | None = None
    failure_code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")] | None = None
    extracted_candidate_count: int = Field(strict=True, ge=0, le=500)

    @field_validator("started_at", "completed_at", "next_retry_at")
    @classmethod
    def require_aware_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("source poll timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_observation_outcome(self) -> SourcePollAttempt:
        if self.completed_at < self.started_at:
            raise ValueError("poll completion cannot precede its start")
        successful = self.outcome in {
            SourcePollOutcome.NEW,
            SourcePollOutcome.CHANGED,
            SourcePollOutcome.UNCHANGED,
        }
        if successful:
            if self.source_observation_id is None or self.snapshot_sha256 is None:
                raise ValueError("successful poll outcomes require a source observation and snapshot")
            if self.failure_code is not None or self.next_retry_at is not None or self.retry_count != 0:
                raise ValueError("successful poll outcomes cannot carry retry state")
            if self.last_successful_snapshot_sha256 != self.snapshot_sha256:
                raise ValueError("successful poll must preserve its latest successful snapshot hash")
        else:
            if self.source_observation_id is not None or self.snapshot_sha256 is not None:
                raise ValueError("unavailable sources cannot claim a successful snapshot observation")
            if self.failure_code is None or self.next_retry_at is None:
                raise ValueError("unavailable sources require a failure code and bounded retry time")
            if self.next_retry_at <= self.completed_at:
                raise ValueError("source poll retry time must follow completion")
            if self.extracted_candidate_count != 0:
                raise ValueError("unavailable sources cannot produce extraction candidates")
            if self.last_successful_snapshot_sha256 != self.previous_snapshot_sha256:
                raise ValueError("failed poll must preserve the prior successful snapshot hash")
        if self.outcome is SourcePollOutcome.NEW and self.previous_snapshot_sha256 is not None:
            raise ValueError("new source observations cannot have a previous snapshot")
        if self.outcome is SourcePollOutcome.CHANGED and (
            self.previous_snapshot_sha256 is None
            or self.previous_snapshot_sha256 == self.snapshot_sha256
        ):
            raise ValueError("changed source observation requires a different previous hash")
        if self.outcome is SourcePollOutcome.UNCHANGED and (
            self.previous_snapshot_sha256 is None
            or self.previous_snapshot_sha256 != self.snapshot_sha256
        ):
            raise ValueError("unchanged source observation must retain its previous hash")
        return self


class SourceDiscoverySummary(ContractModel):
    sources_considered: int = Field(strict=True, ge=0, le=500)
    sources_due: int = Field(strict=True, ge=0, le=500)
    sources_deferred: int = Field(strict=True, ge=0, le=500)
    outcomes: dict[SourcePollOutcome, int]
    candidates_staged: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def counts_match(self) -> SourceDiscoverySummary:
        if self.sources_considered != self.sources_due + self.sources_deferred:
            raise ValueError("considered sources must equal due plus deferred")
        if any(count < 0 for count in self.outcomes.values()):
            raise ValueError("source poll outcome counts cannot be negative")
        if sum(self.outcomes.values()) != self.sources_due:
            raise ValueError("poll outcome counts must equal due source count")
        return self


__all__ = [
    "PollAttemptId",
    "SourceDiscoverySummary",
    "SourcePollAttempt",
    "SourcePollOutcome",
]
