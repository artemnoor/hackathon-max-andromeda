"""Thresholded hierarchical entity selection.

Deterministic resolution remains the default.  A provider is consulted only
after the caller has supplied a large, already narrowed candidate set.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from decimal import Decimal

from ..contracts.hierarchical import (
    HierarchicalSelectionPort,
    SelectionFailureReason,
    SelectionNode,
    SelectionRequest,
    SelectionResult,
    SelectionTree,
)
from ..contracts.public import (
    CandidateMatchReason,
    EntityResolutionCandidate,
    EntityResolutionResult,
    ResolutionEntityType,
    ResolutionStatus,
)


class HierarchicalResolutionService:
    """Resolve a large candidate set through a bounded selection port."""

    def __init__(
        self,
        port: HierarchicalSelectionPort | None = None,
        *,
        candidate_threshold: int = 255,
        definition_version: str = "next-action.v1",
        timeout_seconds: float = 1.5,
    ) -> None:
        if candidate_threshold < 1:
            raise ValueError("candidate threshold must be positive")
        self._port = port
        self._threshold = candidate_threshold
        self._definition_version = definition_version
        self._timeout_seconds = timeout_seconds

    @property
    def candidate_threshold(self) -> int:
        return self._threshold

    def resolve(
        self,
        entity_type: ResolutionEntityType,
        query: str,
        candidates: Sequence[EntityResolutionCandidate],
    ) -> EntityResolutionResult:
        normalized = tuple(candidates)
        self._validate_candidates(entity_type, normalized)
        candidate_hash = compute_candidate_hash(normalized)
        if not normalized:
            return EntityResolutionResult(
                entity_type=entity_type,
                query=query,
                status=ResolutionStatus.NOT_FOUND,
                candidate_hash=candidate_hash,
            )
        if self._port is None or len(normalized) <= self._threshold:
            return _deterministic_result(entity_type, query, normalized, candidate_hash)

        request = SelectionRequest(
            entity_type=entity_type,
            query=query,
            candidates=normalized,
            tree=_build_tree(normalized),
            candidate_threshold=self._threshold,
            definition_version=self._definition_version,
            timeout_seconds=self._timeout_seconds,
        )
        try:
            selected = self._port.select(request)
        except Exception:
            return _ambiguous_result(
                entity_type,
                query,
                normalized,
                candidate_hash,
                reason=SelectionFailureReason.PROVIDER_UNAVAILABLE,
            )
        if selected.candidate_hash != candidate_hash:
            return _ambiguous_result(
                entity_type,
                query,
                normalized,
                candidate_hash,
                reason=SelectionFailureReason.CANDIDATE_TAMPERING,
            )
        candidate_ids = {candidate.canonical_id for candidate in normalized}
        if selected.selected_id is None or selected.selected_id not in candidate_ids:
            reason = selected.failure_reason or SelectionFailureReason.MALFORMED
            return _ambiguous_result(entity_type, query, normalized, candidate_hash, reason=reason)
        selected_candidate = next(candidate for candidate in normalized if candidate.canonical_id == selected.selected_id)
        status = selected.status if selected.status in {ResolutionStatus.EXACT, ResolutionStatus.RESOLVED} else ResolutionStatus.AMBIGUOUS
        return EntityResolutionResult(
            entity_type=entity_type,
            query=query,
            status=status,
            candidates=normalized,
            selected_id=selected_candidate.canonical_id if status is not ResolutionStatus.AMBIGUOUS else None,
            resolution_strategy="jev_tree",
            candidate_hash=candidate_hash,
            resolution_evidence={
                "candidate_threshold": str(self._threshold),
                "model_candidate_requires_confirmation": "true",
            },
        )

    @staticmethod
    def _validate_candidates(entity_type: ResolutionEntityType, candidates: Sequence[EntityResolutionCandidate]) -> None:
        if len(candidates) > 1000:
            raise ValueError("hierarchical candidate budget exceeded")
        ids = [candidate.canonical_id for candidate in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("hierarchical candidates must have unique canonical ids")
        if any(candidate.entity_type is not entity_type for candidate in candidates):
            raise ValueError("hierarchical candidates must share the requested entity type")


def compute_candidate_hash(candidates: Sequence[EntityResolutionCandidate]) -> str:
    payload = "\n".join(
        f"{candidate.canonical_id}|{candidate.label}|{candidate.code or ''}"
        for candidate in sorted(candidates, key=lambda item: item.canonical_id)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_tree(candidates: Sequence[EntityResolutionCandidate]) -> SelectionTree:
    ids = tuple(candidate.canonical_id for candidate in candidates)
    leaves = tuple(
        SelectionNode(node_id=f"leaf-{index // 16:04d}", depth=1, candidate_ids=ids[index : index + 16])
        for index in range(0, len(ids), 16)
    )
    return SelectionTree(
        root=SelectionNode(node_id="root", depth=0, children=leaves),
        max_depth=4,
        max_fanout=16,
    )


def _deterministic_result(
    entity_type: ResolutionEntityType,
    query: str,
    candidates: Sequence[EntityResolutionCandidate],
    candidate_hash: str,
) -> EntityResolutionResult:
    ranked = tuple(sorted(candidates, key=lambda item: (-item.score, item.canonical_id)))
    top = ranked[0]
    plausible = tuple(candidate for candidate in ranked if candidate.score >= top.score - Decimal("0.05"))
    if len(plausible) > 1:
        return _ambiguous_result(entity_type, query, ranked, candidate_hash)
    status = ResolutionStatus.EXACT if top.match_reason is CandidateMatchReason.CANONICAL_ID else ResolutionStatus.RESOLVED
    return EntityResolutionResult(
        entity_type=entity_type,
        query=query,
        status=status,
        candidates=ranked,
        selected_id=top.canonical_id,
        candidate_hash=candidate_hash,
    )


def _ambiguous_result(
    entity_type: ResolutionEntityType,
    query: str,
    candidates: Sequence[EntityResolutionCandidate],
    candidate_hash: str,
    *,
    reason: SelectionFailureReason | None = None,
) -> EntityResolutionResult:
    evidence = {"candidate_hash": candidate_hash}
    if reason is not None:
        evidence["selection_failure"] = reason.value
    return EntityResolutionResult(
        entity_type=entity_type,
        query=query,
        status=ResolutionStatus.AMBIGUOUS,
        candidates=tuple(candidates),
        candidate_hash=candidate_hash,
        resolution_strategy="jev_tree" if reason is not None else "deterministic",
        resolution_evidence=evidence,
    )


__all__ = ["HierarchicalResolutionService", "compute_candidate_hash"]
