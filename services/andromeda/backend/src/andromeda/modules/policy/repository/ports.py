"""Repository and authorization seams for policy revision approval."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from andromeda.shared.contracts.ids import SourceHash

from ..contracts.approval import (
    ApprovedPolicyRevision,
    PolicyApprovalCapability,
    PolicyApprovalEvent,
    PolicyRuleSubmission,
)
from ..contracts.refresh import (
    PolicyProjectionRefreshAttempt,
    PolicyProjectionRefreshCommand,
    PolicyProjectionRefreshKey,
    PolicyProjectionRefreshRecord,
)
from ..contracts.rule import PolicyRuleId, PolicyRuleRevision


class PolicyApprovedSnapshotReader(Protocol):
    """Read a time-bounded set whose every revision is explicitly approved."""

    def list_approved_revision_records(
        self, *, as_known_at: datetime
    ) -> tuple[ApprovedPolicyRevision, ...]: ...

    def list_approved_revisions(
        self, *, as_known_at: datetime
    ) -> tuple[PolicyRuleRevision, ...]: ...


class ApprovedPolicyRuleReader(PolicyApprovedSnapshotReader, Protocol):
    """Read seam whose contract excludes pending/rejected rule revisions."""

    def get_approved_revision(
        self,
        rule_id: PolicyRuleId,
        revision: int,
        *,
        as_known_at: datetime | None = None,
    ) -> PolicyRuleRevision | None: ...


class PolicyReviewPreviewReader(PolicyApprovedSnapshotReader, Protocol):
    """Read-only exact snapshots required for a pending-revision preview."""

    def get_revision(
        self, rule_id: PolicyRuleId, revision: int
    ) -> PolicyRuleRevision | None: ...

    def list_approval_events(
        self,
        rule_id: PolicyRuleId,
        revision: int,
        *,
        as_known_at: datetime | None = None,
    ) -> tuple[PolicyApprovalEvent, ...]: ...


class PolicyRuleRepository(
    ApprovedPolicyRuleReader, PolicyReviewPreviewReader, Protocol
):
    """Persists one rule revision and its initial pending event atomically."""

    def submit_revision(
        self, submission: PolicyRuleSubmission
    ) -> PolicyApprovalEvent: ...

    def get_revision(
        self, rule_id: PolicyRuleId, revision: int
    ) -> PolicyRuleRevision | None: ...

    def list_pending_revisions(
        self, *, limit: int = 100
    ) -> tuple[PolicyRuleRevision, ...]: ...

    def list_approval_events(
        self,
        rule_id: PolicyRuleId,
        revision: int,
        *,
        as_known_at: datetime | None = None,
    ) -> tuple[PolicyApprovalEvent, ...]: ...

    def append_approval_event(
        self, event: PolicyApprovalEvent
    ) -> PolicyApprovalEvent: ...


class PolicyApprovalConflictReader(Protocol):
    """Bounded cross-module read that fails closed when conflicts are unresolved."""

    def has_open_conflicts(
        self,
        rule_id: PolicyRuleId,
        revision: int,
        revision_hash: SourceHash,
    ) -> bool: ...


class PolicyCapabilityAuthorizer(Protocol):
    def require_capability(
        self, actor_account_id: str, capability: PolicyApprovalCapability
    ) -> None: ...


class PolicyProjectionRefreshRepository(Protocol):
    """Idempotent dirty markers and auditable outcomes for targeted rebuilds."""

    def mark_dirty(
        self, command: PolicyProjectionRefreshCommand
    ) -> PolicyProjectionRefreshRecord: ...

    def get_refresh_state(
        self, refresh_key: PolicyProjectionRefreshKey
    ) -> PolicyProjectionRefreshRecord | None: ...

    def list_dirty(
        self, *, limit: int = 100
    ) -> tuple[PolicyProjectionRefreshRecord, ...]: ...

    def record_success(
        self,
        refresh_key: PolicyProjectionRefreshKey,
        *,
        generation: int,
        projection_version: str,
        recorded_at: datetime,
    ) -> PolicyProjectionRefreshRecord: ...

    def record_failure(
        self,
        refresh_key: PolicyProjectionRefreshKey,
        *,
        generation: int,
        failure_code: str,
        recorded_at: datetime,
    ) -> PolicyProjectionRefreshRecord: ...

    def list_attempts(
        self, refresh_key: PolicyProjectionRefreshKey, *, limit: int = 100
    ) -> tuple[PolicyProjectionRefreshAttempt, ...]: ...


__all__ = [
    "PolicyApprovedSnapshotReader",
    "PolicyCapabilityAuthorizer",
    "PolicyProjectionRefreshRepository",
    "PolicyReviewPreviewReader",
    "PolicyRuleRepository",
]
