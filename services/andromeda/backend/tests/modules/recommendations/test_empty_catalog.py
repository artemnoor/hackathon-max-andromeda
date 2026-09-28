from __future__ import annotations

from andromeda.modules.recommendations.contracts.public import RecommendationRequest
from andromeda.modules.recommendations.services.recommendations import RecommendationService
from .factories import profile


class _EmptyReader:
    def list_fingerprints(self):
        return ()


def test_empty_catalog_returns_empty_result_contract() -> None:
    result = RecommendationService(_EmptyReader()).recommend(RecommendationRequest(profile=profile()))
    assert result.recommendations == ()
