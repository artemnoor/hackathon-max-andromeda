"""Stable public surface of the recommendation module."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from andromeda.modules.proftest.contracts.public import (
    ActivityCode,
    AdaptiveAnswer,
    AntiInterest,
    Confidence,
    MatchReason,
    MatchScore,
    Recommendation,
    RecommendationEvidence,
    ReasonKind,
    ScoreBreakdown,
    UserProfile,
)
from andromeda.modules.program_analytics.contracts.public import ProgramFingerprint

from ..domain.entities import RankedFingerprint
from .requests import CandidateRankingRequest, RecommendationRequest
from .results import CandidateRankingResult, RecommendationResult


class ProgramFingerprintReader(Protocol):
    """Read canonical, curriculum-backed fingerprints without storage details."""

    def list_fingerprints(self) -> tuple[ProgramFingerprint, ...]: ...


RecommendationCatalogReader = ProgramFingerprintReader


class RecommendationServicePort(Protocol):
    """Application boundary used by consumers of recommendation orchestration."""

    def rank_fingerprints(
        self,
        profile: UserProfile,
        fingerprints: Iterable[ProgramFingerprint],
        *,
        limit: int | None = None,
    ) -> tuple[RankedFingerprint, ...]: ...

    def rank_candidates(self, request: CandidateRankingRequest) -> CandidateRankingResult: ...

    def build_evidence(
        self,
        profile: UserProfile | None,
        fingerprint: ProgramFingerprint | None,
        *,
        profile_revision: int | None = None,
        question_set_version: str | None = None,
    ) -> RecommendationEvidence: ...

    def recommend_from_fingerprints(
        self,
        request: RecommendationRequest,
        fingerprints: Iterable[ProgramFingerprint],
        *,
        profile_revision: int | None = None,
        question_set_version: str | None = None,
    ) -> RecommendationResult: ...


__all__ = [
    "ActivityCode",
    "AdaptiveAnswer",
    "AntiInterest",
    "CandidateRankingRequest",
    "CandidateRankingResult",
    "Confidence",
    "MatchReason",
    "MatchScore",
    "ProgramFingerprint",
    "Recommendation",
    "RecommendationEvidence",
    "ReasonKind",
    "RecommendationRequest",
    "RecommendationResult",
    "ProgramFingerprintReader",
    "RecommendationCatalogReader",
    "RecommendationServicePort",
    "RankedFingerprint",
    "ScoreBreakdown",
    "UserProfile",
]
