"""Typed, pre-approval differences between captured claim candidates."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .claims import ClaimRevisionRef
from .discovery import SourcePollOutcome
from .sources import SourceId, SourceObservationId

ClaimFingerprint = Annotated[str, StringConstraints(pattern=r"^claim-fingerprint:[a-f0-9]{64}$")]
ClaimCandidateClusterId = Annotated[
    str, StringConstraints(pattern=r"^claim-cluster:[a-f0-9]{64}$")
]


class ClaimDiffKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    UNCHANGED = "unchanged"
    REVISED = "revised"
    AMBIGUOUS = "ambiguous"


class ClaimFieldChange(ContractModel):
    path: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    before: str | None = Field(default=None, max_length=4000)
    after: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def values_differ(self) -> ClaimFieldChange:
        if self.before == self.after:
            raise ValueError("claim field diff must contain distinct values")
        return self


class ClaimCandidateCluster(ContractModel):
    """Exact-assertion group; each source claim and its evidence stays independent."""

    cluster_id: ClaimCandidateClusterId
    fingerprint: ClaimFingerprint
    fingerprint_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    members: tuple[ClaimRevisionRef, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_members(self) -> ClaimCandidateCluster:
        refs = tuple((item.claim_id, item.revision) for item in self.members)
        if len(refs) != len(set(refs)):
            raise ValueError("claim cluster members must be unique")
        return self


class ClaimDiffEntry(ContractModel):
    kind: ClaimDiffKind
    before: tuple[ClaimRevisionRef, ...] = Field(default=(), max_length=500)
    after: tuple[ClaimRevisionRef, ...] = Field(default=(), max_length=500)
    changes: tuple[ClaimFieldChange, ...] = Field(default=(), max_length=32)
    reason_code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]

    @model_validator(mode="after")
    def validate_shape(self) -> ClaimDiffEntry:
        if self.kind is ClaimDiffKind.ADDED and (self.before or not self.after):
            raise ValueError("added claim diffs require only after references")
        if self.kind is ClaimDiffKind.REMOVED and (not self.before or self.after):
            raise ValueError("removed claim diffs require only before references")
        if self.kind is ClaimDiffKind.UNCHANGED and (not self.before or not self.after or self.changes):
            raise ValueError("unchanged claim diffs require matching references and no field changes")
        if self.kind is ClaimDiffKind.REVISED and (
            len(self.before) != 1 or len(self.after) != 1 or not self.changes
        ):
            raise ValueError("revised claim diffs require one before/after pair and field changes")
        if self.kind is ClaimDiffKind.AMBIGUOUS and (not self.before or not self.after):
            raise ValueError("ambiguous claim diffs require candidates on both sides")
        return self


class ClaimSetDiff(ContractModel):
    entries: tuple[ClaimDiffEntry, ...] = Field(max_length=1000)


class SourceObservationDiff(ContractModel):
    source_id: SourceId
    current_attempt_outcome: SourcePollOutcome
    previous_snapshot_sha256: SourceHash | None
    snapshot_sha256: SourceHash | None
    last_successful_snapshot_sha256: SourceHash | None
    previous_observation_id: SourceObservationId | None = None
    current_observation_id: SourceObservationId | None = None
    claim_diff: ClaimSetDiff | None = None

    @model_validator(mode="after")
    def validate_snapshot_diff(self) -> SourceObservationDiff:
        success = self.current_attempt_outcome in {
            SourcePollOutcome.NEW,
            SourcePollOutcome.CHANGED,
            SourcePollOutcome.UNCHANGED,
        }
        if success != (self.current_observation_id is not None and self.snapshot_sha256 is not None):
            raise ValueError("successful source diff requires its current observation and snapshot")
        if not success and self.claim_diff is not None:
            raise ValueError("source availability failures cannot imply candidate removal")
        if self.current_attempt_outcome is SourcePollOutcome.NEW and self.previous_snapshot_sha256 is not None:
            raise ValueError("new source diffs cannot have a prior snapshot")
        if self.current_attempt_outcome is SourcePollOutcome.CHANGED and (
            self.previous_snapshot_sha256 is None
            or self.previous_snapshot_sha256 == self.snapshot_sha256
        ):
            raise ValueError("changed source diffs require distinct prior/current hashes")
        if self.current_attempt_outcome is SourcePollOutcome.UNCHANGED and (
            self.previous_snapshot_sha256 is None
            or self.previous_snapshot_sha256 != self.snapshot_sha256
        ):
            raise ValueError("unchanged source diffs require the same prior/current hash")
        if success and self.last_successful_snapshot_sha256 != self.snapshot_sha256:
            raise ValueError("successful source diff must retain its latest snapshot hash")
        return self


__all__ = [
    "ClaimCandidateCluster",
    "ClaimCandidateClusterId",
    "ClaimDiffEntry",
    "ClaimDiffKind",
    "ClaimFieldChange",
    "ClaimFingerprint",
    "ClaimSetDiff",
    "SourceObservationDiff",
]
