"""Adapter from the Node jev-tree result to the typed backend port."""

from __future__ import annotations

from typing import Any

from andromeda.modules.entity_resolution.contracts.hierarchical import (
    HierarchicalSelectionPort,
    SelectionFailureReason,
    SelectionRequest,
    SelectionResult,
)
from andromeda.modules.entity_resolution.contracts.public import ResolutionStatus
from andromeda.modules.entity_resolution.services.hierarchical import compute_candidate_hash

from .transport import JevTreeTransport


class JevTreeAdapter(HierarchicalSelectionPort):
    """Validate every bridge response; never invent a canonical leaf."""

    def __init__(self, transport: JevTreeTransport) -> None:
        self._transport = transport

    def select(self, request: SelectionRequest) -> SelectionResult:
        candidate_ids = tuple(candidate.canonical_id for candidate in request.candidates)
        expected_hash = compute_candidate_hash(request.candidates)
        if expected_hash != _hash_from_request(request):
            return _failure(candidate_ids, expected_hash, SelectionFailureReason.CANDIDATE_TAMPERING)
        payload = {
            "query": request.query,
            "entityType": request.entity_type.value,
            "candidates": [candidate.model_dump(mode="json") for candidate in request.candidates],
            "tree": request.tree.model_dump(mode="json"),
            "candidateHash": expected_hash,
            "maxFanout": request.tree.max_fanout,
            "maxDepth": request.tree.max_depth,
            "maxCalls": 64,
            "timeoutMs": int(request.timeout_seconds * 1000),
        }
        try:
            response = self._transport.select(payload, timeout_seconds=request.timeout_seconds)
        except Exception:
            return _failure(candidate_ids, expected_hash, SelectionFailureReason.PROVIDER_UNAVAILABLE)
        if response.get("candidateHash") != expected_hash:
            return _failure(candidate_ids, expected_hash, SelectionFailureReason.CANDIDATE_TAMPERING)
        selected_id = response.get("selectedId")
        if selected_id is not None and selected_id not in candidate_ids:
            return _failure(candidate_ids, expected_hash, SelectionFailureReason.CANDIDATE_TAMPERING)
        if not isinstance(selected_id, str):
            return _failure(candidate_ids, expected_hash, _failure_reason(response.get("reason")))
        return SelectionResult(
            status=ResolutionStatus.RESOLVED,
            selected_id=selected_id,
            candidate_ids=candidate_ids,
            strategy="jev_tree",
            candidate_hash=expected_hash,
        )


def _hash_from_request(request: SelectionRequest) -> str:
    return compute_candidate_hash(request.candidates)


def _failure(
    candidate_ids: tuple[str, ...],
    candidate_hash: str,
    reason: SelectionFailureReason,
) -> SelectionResult:
    return SelectionResult(
        status=ResolutionStatus.AMBIGUOUS,
        candidate_ids=candidate_ids,
        strategy="jev_tree",
        candidate_hash=candidate_hash,
        failure_reason=reason,
    )


def _failure_reason(value: Any) -> SelectionFailureReason:
    try:
        return SelectionFailureReason(str(value))
    except ValueError:
        return SelectionFailureReason.MALFORMED


__all__ = ["JevTreeAdapter"]
