"""Stable ranking over scored program fingerprints."""

from __future__ import annotations

from collections.abc import Iterable
import logging

from ..contracts.public import MatchScore, ProgramFingerprint, UserProfile
from ..domain.entities import RankedFingerprint
from .scoring import RecommendationScoringService


logger = logging.getLogger("andromeda.recommendations")


class RankingService:
    def __init__(self, scorer: RecommendationScoringService | None = None) -> None:
        self._scorer = scorer or RecommendationScoringService()

    def rank(
        self,
        profile: UserProfile,
        fingerprints: Iterable[ProgramFingerprint],
        *,
        limit: int | None = None,
    ) -> tuple[RankedFingerprint, ...]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        scored = tuple(RankedFingerprint(fingerprint=fingerprint, score=self._scorer.score(profile, fingerprint)) for fingerprint in fingerprints)
        ordered = tuple(
            sorted(
                scored,
                key=lambda item: (
                    -item.score.content_fit,
                    -item.score.breakdown.subject_fit,
                    item.fingerprint.program_code,
                    item.fingerprint.program_id,
                ),
            )
        )
        if limit is not None:
            ordered = ordered[:limit]
        if not ordered:
            logger.warning("recommendations_catalog_empty")
        else:
            logger.info(
                "recommendations_ranked catalog_size=%d result_count=%d top_fit=%d bottom_fit=%d",
                len(scored), len(ordered), ordered[0].score.content_fit, ordered[-1].score.content_fit,
            )
        return ordered


__all__ = ["RankedFingerprint", "RankingService"]
