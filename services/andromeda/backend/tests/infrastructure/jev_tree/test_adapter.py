from decimal import Decimal

from andromeda.infrastructure.jev_tree.adapter import JevTreeAdapter
from andromeda.modules.entity_resolution.contracts.hierarchical import SelectionNode, SelectionRequest, SelectionTree
from andromeda.modules.entity_resolution.contracts.public import (
    CandidateMatchReason,
    EntityResolutionCandidate,
    ResolutionEntityType,
    ResolutionStatus,
)
from andromeda.modules.entity_resolution.services.hierarchical import compute_candidate_hash


def _request() -> SelectionRequest:
    candidates = tuple(
        EntityResolutionCandidate(
            entity_type=ResolutionEntityType.PROGRAM,
            canonical_id=f"program:{index}",
            label=f"Program {index}",
            match_reason=CandidateMatchReason.TOKEN_MATCH,
            score=Decimal("0.70"),
            confidence=Decimal("0.70"),
        )
        for index in range(2)
    )
    return SelectionRequest(
        entity_type=ResolutionEntityType.PROGRAM,
        query="program",
        candidates=candidates,
        tree=SelectionTree(
            root=SelectionNode(node_id="root", depth=0, candidate_ids=tuple(candidate.canonical_id for candidate in candidates))
        ),
        candidate_threshold=1,
        definition_version="next-action.v1",
    )


class _Transport:
    def __init__(self, selected_id: str | None = "program:1") -> None:
        self.selected_id = selected_id
        self.payload = None

    def select(self, payload, *, timeout_seconds):  # type: ignore[no-untyped-def]
        self.payload = payload
        return {
            "selectedId": self.selected_id,
            "candidateHash": payload["candidateHash"],
            "reason": "model",
        }


def test_adapter_maps_valid_bridge_response_to_typed_result() -> None:
    transport = _Transport()
    result = JevTreeAdapter(transport).select(_request())

    assert result.status is ResolutionStatus.RESOLVED
    assert result.selected_id == "program:1"
    assert transport.payload["candidateHash"] == compute_candidate_hash(_request().candidates)


def test_adapter_rejects_unknown_leaf_without_inventing_selection() -> None:
    transport = _Transport("program:not-in-catalog")
    result = JevTreeAdapter(transport).select(_request())

    assert result.selected_id is None
    assert result.failure_reason.value == "candidate_tampering"

