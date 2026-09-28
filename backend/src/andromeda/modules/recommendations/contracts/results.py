"""Output contracts for recommendation use cases."""

from __future__ import annotations

from pydantic import Field

from andromeda.modules.proftest.contracts.public import Recommendation, UserProfile
from andromeda.shared.contracts.base import ContractModel

from ..domain.entities import RankedFingerprint


class RecommendationResult(ContractModel):
    """Stable result envelope returned by the recommendation application service."""

    profile: UserProfile
    recommendations: tuple[Recommendation, ...] = Field(default_factory=tuple)


class CandidateRankingResult(ContractModel):
    """Existing Content Fit evidence for a bounded, pre-filtered candidate set."""

    ranked: tuple[RankedFingerprint, ...] = Field(default=(), max_length=20)


__all__ = ["CandidateRankingResult", "RecommendationResult"]
