"""Compatibility facade for the recommendation scoring service."""

from andromeda.modules.recommendations.services.scoring import MatchingService, RecommendationScoringService

__all__ = ["MatchingService", "RecommendationScoringService"]
