"""Application facade orchestrating questionnaire, catalog and matching."""

from __future__ import annotations

from decimal import Decimal
import logging

from andromeda.shared.contracts.errors import ValidationError

from ..contracts.public import (
    AnswerSet,
    ProgramFingerprint,
    ProftestPreview,
    ProftestResults,
    PreviewCandidate,
    Question,
    Questionnaire,
    ProfileScope,
    UserProfile,
)
from ..domain.adaptive import AdaptiveSelection
from .adaptive import AdaptiveCandidate, AdaptiveQuestionFactory, AdaptiveQuestionSelector
from .catalog import ProftestCatalogService
from .profile_builder import UserProfileBuilder
from .questionnaire import build_questionnaire
from .profile_persistence import UserProfilePersistenceService
from andromeda.modules.recommendations.contracts.public import (
    RankedFingerprint,
    RecommendationRequest,
    RecommendationServicePort,
)


logger = logging.getLogger("andromeda.proftest.application")

RankedFingerprints = tuple[RankedFingerprint, ...]


class ProftestService:
    def __init__(
        self,
        catalog: ProftestCatalogService,
        recommendations: RecommendationServicePort,
        profile_builder: UserProfileBuilder | None = None,
        profile_persistence: UserProfilePersistenceService | None = None,
    ) -> None:
        self._catalog = catalog
        self._profile_builder = profile_builder or UserProfileBuilder()
        self._recommendations = recommendations
        self._profile_persistence = profile_persistence
        self._adaptive_selector = AdaptiveQuestionSelector()
        self._adaptive_factory = AdaptiveQuestionFactory()

    def questionnaire(self) -> Questionnaire:
        return build_questionnaire()

    def preview(self, answer_set: AnswerSet) -> ProftestPreview:
        questions = self.questionnaire().questions
        profile = self._build_profile(answer_set, questions)
        fingerprints = self._catalog.list_fingerprints()
        ranked = self._rank_all(profile, fingerprints)
        selection = self._select_adaptive(ranked)
        question = self._adaptive_factory.create(selection)
        logger.info("preview_complete fingerprint_count=%d candidate_count=%d adaptive_status=%s", len(fingerprints), len(ranked), selection.status.value)
        return ProftestPreview(profile=profile, adaptive=selection, question=question, candidates=tuple(PreviewCandidate(program_id=item.fingerprint.program_id, program_code=item.fingerprint.program_code, content_fit=item.score.content_fit) for item in ranked[:10]))

    def results(self, answer_set: AnswerSet, profile_scope: ProfileScope | None = None) -> ProftestResults:
        questions = self.questionnaire().questions
        # Adaptive answers are validated only after the current question has
        # been selected from the catalog. Build the base profile from the
        # stable questionnaire answers first so the profile builder does not
        # reject a valid adaptive answer as an unknown question.
        base_profile = self._build_profile(AnswerSet(answers=answer_set.answers), questions)
        fingerprints = self._catalog.list_fingerprints()
        base_ranked = self._rank_all(base_profile, fingerprints)
        selection = self._select_adaptive(base_ranked)
        adaptive_question = self._adaptive_factory.create(selection)
        final_answer_set = answer_set
        if answer_set.adaptive_answers:
            if adaptive_question is None:
                raise ValidationError("Adaptive question is not available for this catalog")
            final_answer_set = self._validate_adaptive_answers(answer_set, adaptive_question)
            profile = self._build_profile(final_answer_set, questions, (adaptive_question,))
        else:
            profile = base_profile
        recommendation_result = self._recommendations.recommend_from_fingerprints(
            self._recommendation_request(profile),
            fingerprints,
        )
        recommendations = recommendation_result.recommendations
        if profile_scope is not None:
            if self._profile_persistence is None:
                raise ValidationError("Profile persistence is not configured")
            snapshot = self._profile_persistence.save_completed(profile_scope, profile)
            logger.info("results_profile_saved revision=%d", snapshot.revision)
        logger.info("results_complete fingerprint_count=%d recommendation_count=%d adaptive_answers=%d", len(fingerprints), len(recommendations), len(answer_set.adaptive_answers))
        return ProftestResults(profile=profile, recommendations=recommendations)

    def _build_profile(
        self,
        answer_set: AnswerSet,
        questions: tuple[Question, ...],
        adaptive_questions: tuple[Question, ...] = (),
    ) -> UserProfile:
        try:
            return self._profile_builder.build(answer_set, questions, adaptive_questions)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def _rank_all(self, profile: UserProfile, fingerprints: tuple[ProgramFingerprint, ...]) -> RankedFingerprints:
        return self._recommendations.rank_fingerprints(profile, fingerprints, limit=max(1, len(fingerprints)))

    def _select_adaptive(self, ranked: RankedFingerprints) -> AdaptiveSelection:
        return self._adaptive_selector.select(tuple(AdaptiveCandidate(fingerprint=item.fingerprint, score=Decimal(item.score.content_fit)) for item in ranked))

    @staticmethod
    def _recommendation_request(profile: UserProfile) -> RecommendationRequest:
        return RecommendationRequest(profile=profile, limit=10)

    @staticmethod
    def _validate_adaptive_answers(answer_set: AnswerSet, question: Question) -> AnswerSet:
        for adaptive_answer in answer_set.adaptive_answers:
            if adaptive_answer.question_id != question.id or adaptive_answer.option_id not in {option.id for option in question.options}:
                raise ValidationError("Adaptive answer does not match the current question")
        return AnswerSet(answers=answer_set.answers, adaptive_answers=answer_set.adaptive_answers)


__all__ = ["ProftestService"]
