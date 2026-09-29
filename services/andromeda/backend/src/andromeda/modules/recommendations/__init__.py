"""Recommendation module public entry point."""

from .contracts.public import CandidateRankingRequest, CandidateRankingResult, RecommendationRequest, RecommendationResult

__all__ = ["CandidateRankingRequest", "CandidateRankingResult", "RecommendationRequest", "RecommendationResult"]
