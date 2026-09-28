"""Repository ports for source identity, approved registry revisions, and observations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import HttpUrl

from andromeda.shared.contracts.ids import SourceHash

from ..contracts.public import (
    ApprovedSourceRegistryRevision,
    ChangeEvent,
    Claim,
    ClaimCandidateCluster,
    ClaimChangeEventId,
    ClaimFingerprint,
    ClaimId,
    ClaimPredicate,
    ConflictParticipantReference,
    EvidenceLocator,
    EvidenceRef,
    KnowledgeClaimLookup,
    KnowledgeClaimRelationRevision,
    KnowledgeConflictAggregate,
    KnowledgeConflictEvent,
    KnowledgeConflictGroupId,
    KnowledgeConflictGroupRevision,
    KnowledgeManualSubmission,
    KnowledgeRelationId,
    KnowledgeRelationKind,
    SourceId,
    SourceIdentity,
    SourceObservation,
    SourceObservationId,
    SourcePollAttempt,
)
from ..contracts.review import (
    KnowledgeReviewActionEvent,
    KnowledgeReviewCapability,
    KnowledgeReviewTargetRef,
    ReviewIdempotencyKey,
)


class SourceRegistryReader(Protocol):
    def get_source_identity(self, source_id: SourceId) -> SourceIdentity | None: ...

    def get_registry_revision(
        self, source_id: SourceId, revision: int
    ) -> ApprovedSourceRegistryRevision | None: ...

    def get_latest_registry_revision(
        self, source_id: SourceId
    ) -> ApprovedSourceRegistryRevision | None: ...

    def list_pollable_registry_revisions(
        self,
    ) -> tuple[ApprovedSourceRegistryRevision, ...]: ...


class SourceRegistryWriter(Protocol):
    def register_source_identity(self, identity: SourceIdentity) -> SourceIdentity: ...

    def append_approved_registry_revision(
        self, revision: ApprovedSourceRegistryRevision
    ) -> ApprovedSourceRegistryRevision: ...


class SourceObservationRepository(Protocol):
    def record_observation(
        self, observation: SourceObservation
    ) -> SourceObservation: ...

    def get_observation(self, observation_id: str) -> SourceObservation | None: ...

    def resolve_snapshot_evidence(
        self,
        *,
        source_url: HttpUrl,
        snapshot_sha256: SourceHash,
        locator: EvidenceLocator,
    ) -> EvidenceRef | None: ...

    def list_observations(
        self, source_id: SourceId, *, limit: int = 100
    ) -> tuple[SourceObservation, ...]: ...


class SourcePollAttemptRepository(Protocol):
    def get_latest_attempt(self, source_id: SourceId) -> SourcePollAttempt | None: ...

    def record_attempt(self, attempt: SourcePollAttempt) -> SourcePollAttempt: ...


class KnowledgeSourceRepository(
    SourceRegistryReader,
    SourceRegistryWriter,
    SourceObservationRepository,
    SourcePollAttemptRepository,
    Protocol,
):
    """Composition-facing port implemented by the infrastructure adapter."""


class KnowledgeManualSubmissionRepository(Protocol):
    """Append-only actor/reason/expiry ledger for manual candidate submissions."""

    def get_by_idempotency_key(
        self, actor_account_id: str, idempotency_key: str
    ) -> KnowledgeManualSubmission | None: ...

    def get_latest_for_target(
        self, target_id: str
    ) -> KnowledgeManualSubmission | None: ...

    def append_submission(
        self, submission: KnowledgeManualSubmission
    ) -> KnowledgeManualSubmission: ...


class KnowledgeManualAuthorization(Protocol):
    def require_source_steward(self, actor_account_id: str) -> None: ...

    def require_university_editor(
        self, actor_account_id: str, university_id: str
    ) -> None: ...


class KnowledgeManualSnapshotCapture(Protocol):
    """Capture-only adapter; implementations must never project canonical data."""

    def capture(
        self,
        *,
        actor_account_id: str,
        registry: ApprovedSourceRegistryRevision,
        requested_url: str,
        content_type: str,
        body: bytes,
        idempotency_key: str,
        captured_at: datetime,
    ) -> SourceObservation: ...


class ClaimRepository(Protocol):
    def append_claim_candidate(self, claim: Claim) -> Claim: ...

    def get_claim_revision(self, claim_id: ClaimId, revision: int) -> Claim | None: ...

    def get_as_known_at(
        self, claim_id: ClaimId, as_known_at: datetime
    ) -> Claim | None: ...

    def list_for_observation(
        self, source_observation_id: SourceObservationId, *, limit: int = 100
    ) -> tuple[Claim, ...]: ...

    def get_exact_claim_cluster(
        self, fingerprint: ClaimFingerprint
    ) -> ClaimCandidateCluster | None: ...

    def list_by_predicate(
        self,
        predicate: ClaimPredicate,
        *,
        as_known_at: datetime,
        subject_id: str | None = None,
        limit: int = 20,
    ) -> tuple[KnowledgeClaimLookup, ...]: ...


class ChangeEventRepository(Protocol):
    def append_change_event_candidate(self, event: ChangeEvent) -> ChangeEvent: ...

    def get_change_event_revision(
        self, event_id: ClaimChangeEventId, revision: int
    ) -> ChangeEvent | None: ...


class KnowledgeCandidateRepository(ClaimRepository, ChangeEventRepository, Protocol):
    """Append-only boundary for source-backed claims and change candidates."""

    def list_pending_claims(self, *, limit: int = 100) -> tuple[Claim, ...]: ...

    def list_pending_change_events(
        self, *, limit: int = 100
    ) -> tuple[ChangeEvent, ...]: ...


class ConflictGroupRepository(Protocol):
    """Immutable source-linked conflict revisions and append-only decisions."""

    def append_conflict_group(
        self, group: KnowledgeConflictGroupRevision
    ) -> KnowledgeConflictGroupRevision: ...

    def get_conflict_group(
        self,
        conflict_id: KnowledgeConflictGroupId,
        revision: int,
    ) -> KnowledgeConflictAggregate | None: ...

    def list_for_participant(
        self,
        participant: ConflictParticipantReference,
        *,
        limit: int = 100,
    ) -> tuple[KnowledgeConflictAggregate, ...]: ...

    def append_conflict_event(
        self, event: KnowledgeConflictEvent
    ) -> KnowledgeConflictEvent: ...


class KnowledgeRelationRepository(Protocol):
    """Append-only typed claim edges; readers choose accepted edges explicitly."""

    def append_relation(
        self, relation: KnowledgeClaimRelationRevision
    ) -> KnowledgeClaimRelationRevision: ...

    def get_relation(
        self, relation_id: KnowledgeRelationId, revision: int
    ) -> KnowledgeClaimRelationRevision | None: ...

    def list_relations(
        self,
        claim_id: ClaimId,
        *,
        kinds: tuple[KnowledgeRelationKind, ...] = (),
        include_incoming: bool = True,
        approved_only: bool = True,
        limit: int = 1000,
    ) -> tuple[KnowledgeClaimRelationRevision, ...]: ...


class KnowledgeReviewCandidateRepository(Protocol):
    """Owner-side writes for exact review outcomes; raw candidate writes stay pending-only."""

    def get_claim_revision(self, claim_id: ClaimId, revision: int) -> Claim | None: ...

    def get_change_event_revision(
        self, event_id: ClaimChangeEventId, revision: int
    ) -> ChangeEvent | None: ...

    def append_claim_candidate(self, claim: Claim) -> Claim: ...

    def append_reviewed_claim_revision(self, claim: Claim) -> Claim: ...

    def append_change_event_candidate(self, event: ChangeEvent) -> ChangeEvent: ...

    def append_reviewed_change_event_revision(
        self, event: ChangeEvent
    ) -> ChangeEvent: ...


class KnowledgeReviewActionRepository(Protocol):
    """Append-only review action history; policy decisions remain in policy's ledger."""

    def get_action_by_idempotency_key(
        self, actor_account_id: str, idempotency_key: ReviewIdempotencyKey
    ) -> KnowledgeReviewActionEvent | None: ...

    def append_action(
        self, event: KnowledgeReviewActionEvent
    ) -> KnowledgeReviewActionEvent: ...

    def list_actions(
        self, target: KnowledgeReviewTargetRef, *, limit: int = 100
    ) -> tuple[KnowledgeReviewActionEvent, ...]: ...


class KnowledgeReviewAuthorizer(Protocol):
    def require_capability(
        self,
        actor_account_id: str,
        capability: KnowledgeReviewCapability,
        target: KnowledgeReviewTargetRef,
    ) -> None: ...


class KnowledgeReviewUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


__all__ = [
    "ChangeEventRepository",
    "ClaimRepository",
    "ConflictGroupRepository",
    "KnowledgeCandidateRepository",
    "KnowledgeManualAuthorization",
    "KnowledgeManualSnapshotCapture",
    "KnowledgeManualSubmissionRepository",
    "KnowledgeRelationRepository",
    "KnowledgeReviewActionRepository",
    "KnowledgeReviewAuthorizer",
    "KnowledgeReviewCandidateRepository",
    "KnowledgeReviewUnitOfWork",
    "KnowledgeSourceRepository",
    "SourceObservationRepository",
    "SourcePollAttemptRepository",
    "SourceRegistryReader",
    "SourceRegistryWriter",
]
