"""Infrastructure adapter exposing curriculum fingerprints to recommendations."""

from __future__ import annotations

import logging

from andromeda.modules.proftest.contracts.public import ProgramFingerprint
from andromeda.modules.proftest.services.catalog import ProftestCatalogService
from andromeda.modules.recommendations.repository.ports import RecommendationCatalogReader


logger = logging.getLogger("andromeda.recommendations")


class CatalogRecommendationRepository(RecommendationCatalogReader):
    """Delegate fingerprint construction to the existing canonical catalog path."""

    def __init__(self, catalog: ProftestCatalogService) -> None:
        self._catalog = catalog

    def list_fingerprints(self) -> tuple[ProgramFingerprint, ...]:
        logger.debug("recommendations_catalog_adapter_start")
        fingerprints = self._catalog.list_fingerprints()
        logger.info("recommendations_catalog_adapter_complete fingerprint_count=%d", len(fingerprints))
        return fingerprints


__all__ = ["CatalogRecommendationRepository"]
