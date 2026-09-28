"""Owner-bound persistence port for generic query sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
    AdmissionBenefitPolicyEvaluation,
    AdmissionBenefitPolicyEvaluationRequest,
)
from andromeda.modules.knowledge.contracts.public import (
    ClaimPredicate,
    ClaimRevisionRef,
    KnowledgeClaimLookup,
)
from andromeda.modules.policy.contracts.public import PolicyCycleComparison
from andromeda.modules.policy.contracts.resolution import (
    PolicyResolutionRequest,
    ResolutionTrace,
)
from andromeda.modules.proftest.contracts.public import ProfileScope

from .public import QuerySession, QuerySessionId


class QuerySessionRepository(Protocol):
    def get(
        self, session_id: QuerySessionId, *, owner_scope: ProfileScope
    ) -> QuerySession | None: ...

    def save(
        self, session: QuerySession, *, expected_revision: int | None = None
    ) -> QuerySession: ...

    def purge_expired(
        self, *, now: datetime | None = None, limit: int = 500
    ) -> int: ...


class PolicyQueryResolver(Protocol):
    """Consumer-facing typed seam to deterministic approved-only policy resolution."""

    def resolve(self, request: PolicyResolutionRequest) -> ResolutionTrace: ...

    def resolve_for_claims(
        self,
        request: PolicyResolutionRequest,
        claim_refs: tuple[ClaimRevisionRef, ...],
    ) -> ResolutionTrace: ...

    def resolve_for_admission_cycle(
        self,
        request: PolicyResolutionRequest,
        claim_refs: tuple[ClaimRevisionRef, ...],
    ) -> ResolutionTrace: ...

    def compare_for_claims(
        self,
        request: PolicyResolutionRequest,
        admission_years: tuple[int, int],
        claim_refs: tuple[ClaimRevisionRef, ...],
    ) -> PolicyCycleComparison: ...


class KnowledgeClaimLookupReader(Protocol):
    """Bounded read seam for source assertions matched by a registered predicate."""

    def list_by_predicate(
        self,
        predicate: ClaimPredicate,
        *,
        as_known_at: datetime,
        subject_id: str | None = None,
        limit: int = 20,
    ) -> tuple[KnowledgeClaimLookup, ...]: ...


class AdmissionBenefitPolicyEvaluator(Protocol):
    """Owner handoff for exact approved policy-selected admission-benefit rules."""

    def evaluate(
        self, request: AdmissionBenefitPolicyEvaluationRequest
    ) -> AdmissionBenefitPolicyEvaluation: ...


__all__ = [
    "AdmissionBenefitPolicyEvaluator",
    "KnowledgeClaimLookupReader",
    "PolicyQueryResolver",
    "QuerySessionRepository",
]
