from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.entity_resolution.contracts.public import (
    CandidateMatchReason,
    EntityResolutionCandidate,
    EntityResolutionResult,
    ResolutionEntityType,
    ResolutionStatus,
)


def _candidate(canonical_id: str, label: str, score: str = "1") -> EntityResolutionCandidate:
    return EntityResolutionCandidate(
        entity_type=ResolutionEntityType.UNIVERSITY,
        canonical_id=canonical_id,
        label=label,
        match_reason=CandidateMatchReason.ALIAS,
        score=Decimal(score),
        confidence=Decimal(score),
    )


def test_exact_resolution_has_explicit_selected_canonical_id() -> None:
    candidate = _candidate("university:bmstu", "МГТУ им. Н. Э. Баумана")
    result = EntityResolutionResult(
        entity_type=ResolutionEntityType.UNIVERSITY,
        query="Бауманка",
        status=ResolutionStatus.EXACT,
        candidates=(candidate,),
        selected_id=candidate.canonical_id,
    )

    assert result.selected_id == "university:bmstu"


def test_ambiguous_resolution_carries_candidates_without_silent_choice() -> None:
    candidates = (
        _candidate("university:bmstu", "Бауманка", "0.8"),
        _candidate("university:bmstu-branch", "Бауманка филиал", "0.8"),
    )
    result = EntityResolutionResult(
        entity_type=ResolutionEntityType.UNIVERSITY,
        query="Бауманка",
        status=ResolutionStatus.AMBIGUOUS,
        candidates=candidates,
    )

    assert result.selected_id is None
    assert tuple(candidate.canonical_id for candidate in result.candidates) == (
        "university:bmstu",
        "university:bmstu-branch",
    )


def test_resolution_rejects_missing_selection_and_not_found_candidates() -> None:
    with pytest.raises(ValidationError):
        EntityResolutionResult(
            entity_type=ResolutionEntityType.PROGRAM,
            query="ПИ",
            status=ResolutionStatus.RESOLVED,
        )
    with pytest.raises(ValidationError):
        EntityResolutionResult(
            entity_type=ResolutionEntityType.PROGRAM,
            query="ПИ",
            status=ResolutionStatus.NOT_FOUND,
            candidates=(_candidate("program:bmstu:09.03.01-02", "ПИ"),),
        )
