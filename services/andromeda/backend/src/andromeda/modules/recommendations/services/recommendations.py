"""Application service for the recommendation vertical slice."""

from __future__ import annotations

from collections.abc import Iterable
import logging

from andromeda.shared.contracts.errors import ContractError, ErrorCode

from ..contracts.public import (
    CandidateRankingRequest,
    CandidateRankingResult,
    MatchScore,
    ProgramFingerprint,
    Recommendation,
    RecommendationEvidence,
    RecommendationRequest,
    RecommendationResult,
    ReasonKind,
    UserProfile,
)
from ..repository.ports import RecommendationCatalogReader
from .explanations import ExplanationBuilder
from .evidence import RecommendationEvidenceService
from .ranking import RankedFingerprint, RankingService
from .scoring import RecommendationScoringService


logger = logging.getLogger("andromeda.recommendations")


class RecommendationService:
    """Orchestrate catalog reading, scoring, ranking and explanations."""

    def __init__(
        self,
        reader: RecommendationCatalogReader,
        scorer: RecommendationScoringService | None = None,
        ranking: RankingService | None = None,
        explanations: ExplanationBuilder | None = None,
        evidence: RecommendationEvidenceService | None = None,
    ) -> None:
        self._reader = reader
        self._scorer = scorer or RecommendationScoringService()
        self._ranking = ranking or RankingService(self._scorer)
        self._explanations = explanations or ExplanationBuilder()
        self._evidence = evidence or RecommendationEvidenceService()

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        try:
            fingerprints = tuple(self._reader.list_fingerprints())
        except Exception:
            logger.exception("recommendations_catalog_read_failed")
            raise
        logger.debug("recommendations_catalog_read catalog_size=%d limit=%d", len(fingerprints), request.limit)
        return self.recommend_from_fingerprints(request, fingerprints)

    def recommend_from_fingerprints(
        self,
        request: RecommendationRequest,
        fingerprints: Iterable[ProgramFingerprint],
        *,
        profile_revision: int | None = None,
        question_set_version: str | None = None,
    ) -> RecommendationResult:
        """Build a result from one already-read canonical snapshot."""

        fingerprint_snapshot = tuple(fingerprints)
        ranked = self.rank_fingerprints(request.profile, fingerprint_snapshot, limit=request.limit)
        recommendations = tuple(
            self._recommendation(
                request.profile,
                item.fingerprint,
                item.score,
                profile_revision=profile_revision,
                question_set_version=question_set_version,
            )
            for item in ranked
        )
        if not recommendations:
            logger.warning("recommendations_empty_result catalog_size=%d", len(fingerprint_snapshot))
        logger.info(
            "recommendations_complete catalog_size=%d requested_limit=%d result_count=%d top_score=%s",
            len(fingerprint_snapshot), request.limit, len(recommendations), recommendations[0].content_fit if recommendations else "none",
        )
        return RecommendationResult(profile=request.profile, recommendations=recommendations)

    def rank_fingerprints(
        self,
        profile: "UserProfile",
        fingerprints: Iterable[ProgramFingerprint],
        *,
        limit: int | None = None,
    ) -> tuple[RankedFingerprint, ...]:
        return self._ranking.rank(profile, fingerprints, limit=limit)

    def rank_candidates(self, request: CandidateRankingRequest) -> CandidateRankingResult:
        logger.debug(
            "recommendations_candidate_ranking_start candidate_count=%d limit=%d",
            len(request.fingerprints),
            request.limit,
        )
        ranked = self.rank_fingerprints(request.profile, request.fingerprints, limit=request.limit)
        result = CandidateRankingResult(ranked=ranked)
        logger.info("recommendations_candidate_ranking_complete result_count=%d", len(result.ranked))
        return result

    def build_evidence(
        self,
        profile: "UserProfile" | None,
        fingerprint: ProgramFingerprint | None,
        *,
        profile_revision: int | None = None,
        question_set_version: str | None = None,
    ) -> RecommendationEvidence:
        return self._evidence.build(
            profile,
            fingerprint,
            profile_revision=profile_revision,
            question_set_version=question_set_version,
        )

    def _recommendation(
        self,
        profile: "UserProfile",
        fingerprint: ProgramFingerprint,
        score: MatchScore,
        *,
        profile_revision: int | None = None,
        question_set_version: str | None = None,
    ) -> Recommendation:
        if not isinstance(fingerprint, ProgramFingerprint):
            program_id = getattr(fingerprint, "program_id", "unknown")
            logger.error("recommendations_fingerprint_contract_invalid program_id=%s", _safe_id(str(program_id)))
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Program fingerprint contract is incompatible")
        reasons = self._explanations.build(profile, fingerprint)
        evidence = self.build_evidence(
            profile,
            fingerprint,
            profile_revision=profile_revision,
            question_set_version=question_set_version,
        )
        return Recommendation.from_fingerprint(fingerprint, score).model_copy(
            update={
                "reasons": tuple(reason for reason in reasons if reason.kind is ReasonKind.FIT),
                "anti_fit_reasons": tuple(reason for reason in reasons if reason.kind is ReasonKind.ANTI_FIT),
                "evidence": evidence,
            }
        )


def _safe_id(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")[:128]


__all__ = ["RecommendationService"]
