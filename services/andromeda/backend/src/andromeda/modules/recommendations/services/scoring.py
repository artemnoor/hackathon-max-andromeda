"""Deterministic, explainable Content Fit scoring."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import logging

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode

from ..contracts.public import ActivityCode, MatchScore, ProgramFingerprint, ScoreBreakdown, UserProfile
from ..domain.policy import RecommendationPolicy
from ..domain.signals import ACTIVITY_SIGNAL_WEIGHTS


logger = logging.getLogger("andromeda.recommendations")
ZERO = Decimal("0")


class RecommendationScoringService:
    """Calculate one bounded score from public profile and fingerprint contracts."""

    def __init__(self, policy: RecommendationPolicy | None = None) -> None:
        self._policy = policy or RecommendationPolicy()

    def score(self, profile: UserProfile, fingerprint: ProgramFingerprint) -> MatchScore:
        subject_fit = self._subject_fit(profile, fingerprint)
        activity_fit = self._activity_fit(profile, fingerprint)
        distinctive_fit = self._distinctive_fit(profile, fingerprint)
        anti_penalty = self._anti_penalty(profile, fingerprint)
        weights = self._policy.weights
        raw = weights.subject * subject_fit + weights.activity * activity_fit + weights.distinctive * distinctive_fit - weights.anti_interest * anti_penalty
        result = MatchScore(
            program_id=fingerprint.program_id,
            program_code=fingerprint.program_code,
            content_fit=_round_clamp(raw, self._policy),
            breakdown=ScoreBreakdown(
                subject_fit=subject_fit,
                activity_fit=activity_fit,
                distinctive_fit=distinctive_fit,
                anti_penalty=anti_penalty,
                raw_content_fit=raw,
            ),
        )
        logger.debug(
            "recommendation_score program_id=%s subject_fit=%.2f activity_fit=%.2f distinctive_fit=%.2f anti_penalty=%.2f content_fit=%d",
            _safe_id(fingerprint.program_id), subject_fit, activity_fit, distinctive_fit, anti_penalty, result.content_fit,
        )
        return result

    @staticmethod
    def _subject_fit(profile: UserProfile, fingerprint: ProgramFingerprint) -> Decimal:
        if not profile.preferred_subject_weights:
            return Decimal("50")
        return Decimal("100") * sum((fingerprint.area_share.get(area, ZERO) * weight for area, weight in profile.preferred_subject_weights.items()), ZERO)

    @staticmethod
    def _activity_fit(profile: UserProfile, fingerprint: ProgramFingerprint) -> Decimal:
        if not profile.preferred_activity_weights:
            return Decimal("50")
        return Decimal("100") * sum((fingerprint.activity_signals.get(activity, ZERO) * weight for activity, weight in profile.preferred_activity_weights.items()), ZERO)

    @staticmethod
    def _distinctive_fit(profile: UserProfile, fingerprint: ProgramFingerprint) -> Decimal:
        if not fingerprint.distinctive_subjects or (not profile.preferred_subject_weights and not profile.preferred_activity_weights):
            return Decimal("50")
        total_weight = sum((subject.distinctiveness for subject in fingerprint.distinctive_subjects), ZERO)
        if total_weight <= ZERO:
            return Decimal("50")
        overlap = ZERO
        for subject in fingerprint.distinctive_subjects:
            subject_affinity = profile.preferred_subject_weights.get(subject.primary_area, ZERO)
            activity_affinity = sum(
                (profile.preferred_activity_weights.get(activity, ZERO) * weight for activity, weight in ACTIVITY_SIGNAL_WEIGHTS.get(subject.primary_area, {}).items()),
                ZERO,
            )
            overlap += subject.distinctiveness * (Decimal("0.70") * subject_affinity + Decimal("0.30") * activity_affinity)
        return Decimal("100") * overlap / total_weight

    @staticmethod
    def _anti_penalty(profile: UserProfile, fingerprint: ProgramFingerprint) -> Decimal:
        if not profile.negative_weights:
            return ZERO
        return Decimal("100") * sum((fingerprint.area_share.get(area, ZERO) * weight for area, weight in profile.negative_weights.items()), ZERO)


def _round_clamp(value: Decimal, policy: RecommendationPolicy) -> int:
    rounded = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(policy.score_min, min(policy.score_max, rounded))


def _safe_id(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")[:128]


MatchingService = RecommendationScoringService

__all__ = ["MatchingService", "RecommendationScoringService"]
