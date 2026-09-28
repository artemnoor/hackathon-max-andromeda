"""Current-session recommendation use case."""

from __future__ import annotations

import logging

from andromeda.modules.proftest.contracts.public import CurrentUserProfileReader, ProfileScope
from andromeda.shared.contracts.errors import NotFoundError

from ..contracts.public import RecommendationRequest, RecommendationResult
from .recommendations import RecommendationService


logger = logging.getLogger("andromeda.recommendations.current")


class CurrentRecommendationService:
    """Reuse the existing Content Fit service for the current persisted profile."""

    def __init__(self, profile_reader: CurrentUserProfileReader, recommendations: RecommendationService) -> None:
        self._profile_reader = profile_reader
        self._recommendations = recommendations

    def recommend(self, scope: ProfileScope, *, limit: int) -> RecommendationResult:
        logger.debug("current_recommendations_start limit=%d", limit)
        snapshot = self._profile_reader.get_current(scope)
        if snapshot is None:
            logger.warning("current_recommendations_empty outcome=profile_not_found")
            raise NotFoundError("Current profile was not found")
        result = self._recommendations.recommend(RecommendationRequest(profile=snapshot.profile, limit=limit))
        logger.info("current_recommendations_complete revision=%d result_count=%d", snapshot.revision, len(result.recommendations))
        return result


__all__ = ["CurrentRecommendationService"]
