"""Targeted, idempotent refresh state for rebuildable policy projections."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .applicability import PolicySelection
from .dependencies import PolicyDependencyNode

PolicyProjectionRefreshKey = Annotated[
    str, StringConstraints(pattern=r"^policy-refresh:[a-f0-9]{64}$")
]
PolicyProjectionRefreshAttemptId = Annotated[
    str, StringConstraints(pattern=r"^policy-refresh-attempt:[a-f0-9]{64}$")
]


class PolicyProjectionKind(StrEnum):
    EFFECTIVE_POLICY = "effective_policy"
    DOMAIN_IMPACT = "domain_impact"
    DEPENDENCY_CLOSURE = "dependency_closure"


class PolicyProjectionRefreshState(StrEnum):
    DIRTY = "dirty"
    READY = "ready"
    FAILED = "failed"


class PolicyProjectionRefreshOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    STALE_RESULT_REJECTED = "stale_result_rejected"


class PolicyProjectionRefreshCommand(ContractModel):
    target: PolicyDependencyNode
    projection_kind: PolicyProjectionKind
    invalidated_by: tuple[PolicySelection, ...] = Field(min_length=1, max_length=32)
    invalidated_at: datetime

    @field_validator("invalidated_at")
    @classmethod
    def normalize_invalidated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("projection invalidated_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def invalidators_are_exact_and_unique(self) -> PolicyProjectionRefreshCommand:
        identities = {
            (item.rule_id, item.revision, item.revision_hash)
            for item in self.invalidated_by
        }
        if len(identities) != len(self.invalidated_by):
            raise ValueError("projection invalidators must be unique exact revisions")
        if tuple(sorted(self.invalidated_by, key=_selection_key)) != self.invalidated_by:
            raise ValueError("projection invalidators must use canonical order")
        return self


class PolicyProjectionRefreshRecord(ContractModel):
    refresh_key: PolicyProjectionRefreshKey
    target: PolicyDependencyNode
    projection_kind: PolicyProjectionKind
    generation: int = Field(strict=True, ge=1, le=2_147_483_647)
    completed_generation: int = Field(strict=True, ge=0, le=2_147_483_647)
    invalidated_by: tuple[PolicySelection, ...] = Field(min_length=1, max_length=32)
    invalidation_fingerprint: SourceHash
    state: PolicyProjectionRefreshState
    projection_version: SourceHash | None = None
    attempt_count: int = Field(strict=True, ge=0, le=2_147_483_647)
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_updated_at: datetime
    failure_code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")] | None = None

    @field_validator("last_attempt_at", "last_success_at", "last_updated_at")
    @classmethod
    def normalize_refresh_time(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("projection refresh timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def state_matches_generation(self) -> PolicyProjectionRefreshRecord:
        identities = {
            (item.rule_id, item.revision, item.revision_hash)
            for item in self.invalidated_by
        }
        if len(identities) != len(self.invalidated_by):
            raise ValueError("projection invalidators must be unique exact revisions")
        if tuple(sorted(self.invalidated_by, key=_selection_key)) != self.invalidated_by:
            raise ValueError("projection invalidators must use canonical order")
        if self.completed_generation > self.generation:
            raise ValueError("projection completed generation cannot exceed dirty generation")
        if self.state is PolicyProjectionRefreshState.READY:
            if (
                self.completed_generation != self.generation
                or self.projection_version is None
                or self.last_success_at is None
                or self.failure_code is not None
            ):
                raise ValueError("ready projection must match its latest generation and version")
        elif self.state is PolicyProjectionRefreshState.DIRTY:
            if self.completed_generation == self.generation or self.failure_code is not None:
                raise ValueError("dirty projection must have pending generation and no failure code")
        elif self.completed_generation == self.generation or self.failure_code is None:
            raise ValueError("failed projection must retain a pending generation and failure code")
        if self.refresh_key != policy_projection_refresh_key(
            self.projection_kind, self.target
        ):
            raise ValueError("projection refresh key does not match its typed target")
        return self


class PolicyProjectionRefreshAttempt(ContractModel):
    attempt_id: PolicyProjectionRefreshAttemptId
    refresh_key: PolicyProjectionRefreshKey
    sequence: int = Field(strict=True, ge=1, le=2_147_483_647)
    generation: int = Field(strict=True, ge=1, le=2_147_483_647)
    outcome: PolicyProjectionRefreshOutcome
    projection_version: SourceHash | None = None
    failure_code: str | None = Field(default=None, max_length=64)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def normalize_attempt_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("projection refresh attempt time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_attempt_result_shape(self) -> PolicyProjectionRefreshAttempt:
        if self.outcome is PolicyProjectionRefreshOutcome.COMPLETED:
            if self.projection_version is None or self.failure_code is not None:
                raise ValueError("completed projection attempt requires version and no failure")
        elif self.outcome is PolicyProjectionRefreshOutcome.FAILED:
            if self.failure_code is None or self.projection_version is not None:
                raise ValueError("failed projection attempt requires a failure code")
        elif self.failure_code is None or self.projection_version is None:
            raise ValueError("stale projection result audit requires expected version and rejection code")
        if self.attempt_id != policy_projection_refresh_attempt_id(
            self.refresh_key,
            self.sequence,
            self.generation,
            self.outcome,
            self.projection_version,
            self.failure_code,
        ):
            raise ValueError("projection refresh attempt ID does not match its immutable outcome")
        return self


def policy_projection_refresh_key(
    projection_kind: PolicyProjectionKind,
    target: PolicyDependencyNode,
) -> PolicyProjectionRefreshKey:
    payload = {"projection_kind": projection_kind.value, "target": target.identity()}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"policy-refresh:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def policy_projection_invalidation_fingerprint(
    command: PolicyProjectionRefreshCommand,
) -> SourceHash:
    payload = {
        "refresh_key": policy_projection_refresh_key(command.projection_kind, command.target),
        "invalidated_by": [
            (item.rule_id, item.revision, item.revision_hash)
            for item in command.invalidated_by
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _selection_key(selection: PolicySelection) -> tuple[str, int, str]:
    return selection.rule_id, selection.revision, selection.revision_hash


def policy_projection_refresh_attempt_id(
    refresh_key: PolicyProjectionRefreshKey,
    sequence: int,
    generation: int,
    outcome: PolicyProjectionRefreshOutcome,
    projection_version: SourceHash | None,
    failure_code: str | None,
) -> PolicyProjectionRefreshAttemptId:
    payload = {
        "refresh_key": refresh_key,
        "sequence": sequence,
        "generation": generation,
        "outcome": outcome.value,
        "projection_version": projection_version,
        "failure_code": failure_code,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"policy-refresh-attempt:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


__all__ = [
    "PolicyProjectionKind",
    "PolicyProjectionRefreshAttempt",
    "PolicyProjectionRefreshAttemptId",
    "PolicyProjectionRefreshCommand",
    "PolicyProjectionRefreshKey",
    "PolicyProjectionRefreshOutcome",
    "PolicyProjectionRefreshRecord",
    "PolicyProjectionRefreshState",
    "policy_projection_invalidation_fingerprint",
    "policy_projection_refresh_attempt_id",
    "policy_projection_refresh_key",
]
