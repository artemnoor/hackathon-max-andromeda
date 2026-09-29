from __future__ import annotations

from andromeda.modules.recommendations.repository.ports import RecommendationCatalogReader


def test_reader_contract_exposes_only_fingerprint_snapshot() -> None:
    assert hasattr(RecommendationCatalogReader, "list_fingerprints")
    assert not hasattr(RecommendationCatalogReader, "get_curriculum")
