from decimal import Decimal

from andromeda.modules.entity_resolution.contracts.hierarchical import SelectionResult
from andromeda.modules.entity_resolution.contracts.public import (
    CandidateMatchReason,
    EntityResolutionCandidate,
    ResolutionEntityType,
    ResolutionStatus,
)
from andromeda.modules.entity_resolution.services.hierarchical import HierarchicalResolutionService


def _candidates(count: int) -> tuple[EntityResolutionCandidate, ...]:
    return tuple(
        EntityResolutionCandidate(
            entity_type=ResolutionEntityType.PROGRAM,
            canonical_id=f"program:{index}",
            label=f"Program {index}",
            match_reason=CandidateMatchReason.TOKEN_MATCH,
            score=Decimal("0.70"),
            confidence=Decimal("0.70"),
        )
        for index in range(count)
    )


class _FakeSelectionPort:
    def __init__(self, selected_id: str | None = None, *, wrong_hash: bool = False) -> None:
        self.requests = []
        self.selected_id = selected_id
        self.wrong_hash = wrong_hash

    def select(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return SelectionResult(
            status=ResolutionStatus.RESOLVED,
            selected_id=self.selected_id,
            candidate_ids=tuple(candidate.canonical_id for candidate in request.candidates),
            strategy="jev_tree",
            candidate_hash="tampered" if self.wrong_hash else _hash_for(request.candidates),
        )


def _hash_for(candidates) -> str:  # type: ignore[no-untyped-def]
    from andromeda.modules.entity_resolution.services.hierarchical import compute_candidate_hash

    return compute_candidate_hash(candidates)


def test_small_candidate_set_never_calls_hierarchical_provider() -> None:
    port = _FakeSelectionPort("program:1")
    result = HierarchicalResolutionService(port).resolve(
        ResolutionEntityType.PROGRAM,
        "program 1",
        _candidates(20),
    )

    assert not port.requests
    assert result.resolution_strategy == "deterministic"
    assert result.status is ResolutionStatus.AMBIGUOUS


def test_large_candidate_set_uses_stable_bounded_tree() -> None:
    port = _FakeSelectionPort("program:270")
    result = HierarchicalResolutionService(port).resolve(
        ResolutionEntityType.PROGRAM,
        "program",
        _candidates(300),
    )

    assert len(port.requests) == 1
    request = port.requests[0]
    assert len(request.tree.root.children) == 19
    assert result.selected_id == "program:270"
    assert result.resolution_strategy == "jev_tree"
    assert result.resolution_evidence["model_candidate_requires_confirmation"] == "true"


def test_tampered_candidate_hash_does_not_select_model_output() -> None:
    port = _FakeSelectionPort("program:270", wrong_hash=True)
    result = HierarchicalResolutionService(port).resolve(
        ResolutionEntityType.PROGRAM,
        "program",
        _candidates(300),
    )

    assert result.selected_id is None
    assert result.status is ResolutionStatus.AMBIGUOUS
    assert result.resolution_evidence["selection_failure"] == "candidate_tampering"
