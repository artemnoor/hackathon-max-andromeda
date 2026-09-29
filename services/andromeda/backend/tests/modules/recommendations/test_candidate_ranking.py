from __future__ import annotations

from pydantic import ValidationError
import pytest

from andromeda.modules.recommendations.contracts.public import CandidateRankingRequest, CandidateRankingResult
from andromeda.modules.recommendations.services.recommendations import RecommendationService

from .factories import fingerprint, profile


class Reader:
    def list_fingerprints(self):
        return ()


def test_candidate_ranking_uses_only_supplied_fingerprints_and_is_deterministic() -> None:
    request = CandidateRankingRequest(
        profile=profile(),
        fingerprints=(fingerprint("09.03.01-12"), fingerprint("09.03.01-02")),
        limit=2,
    )
    service = RecommendationService(Reader())

    first = service.rank_candidates(request)
    second = service.rank_candidates(request)

    assert isinstance(first, CandidateRankingResult)
    assert first == second
    assert {item.fingerprint.program_code for item in first.ranked} == {"09.03.01-12", "09.03.01-02"}


def test_candidate_ranking_rejects_duplicate_ids_and_unbounded_limit() -> None:
    with pytest.raises(ValidationError):
        CandidateRankingRequest(
            profile=profile(),
            fingerprints=(fingerprint(), fingerprint()),
        )
    with pytest.raises(ValidationError):
        CandidateRankingRequest(profile=profile(), limit=21)
