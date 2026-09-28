"""Application orchestration for the adaptive proftest session API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging

from andromeda.modules.disciplines.contracts.public import area_definition
from andromeda.modules.recommendations.contracts.public import RankedFingerprint, RecommendationRequest, RecommendationServicePort
from andromeda.shared.contracts.errors import ConflictError, NotFoundError, ValidationError

from ..contracts.public import (
    AdaptiveAnswer,
    AdaptiveSelection,
    AdaptiveState,
    AnswerSet,
    AnswerStatus,
    AnalyticsEventType,
    ProfileScope,
    ProftestAnalyticsEvent,
    ProftestAnswerSession,
    ProftestResults,
    ProftestSessionView,
    PreliminaryProfile,
    PreliminaryTopic,
    Question,
    QuestionStage,
    SessionAnswer,
    SessionProgress,
    SessionStatus,
    UserProfile,
    CurrentUserProfileReader,
)
from ..domain.questions import Questionnaire
from ..repository.ports import ProftestAnalyticsWriter, ProftestAnswerSessionRepository
from .adaptive import AdaptiveCandidate, AdaptiveQuestionFactory, AdaptiveQuestionSelector
from .adaptive import MAX_ADAPTIVE_QUESTIONS_V2, MAX_ADAPTIVE_QUESTIONS_V3, MIN_ADAPTIVE_ANSWERS_BEFORE_STOP_V3, TOP_THREE_SCORE_DELTA_V3
from .catalog import ProftestCatalogService
from .profile_builder import UserProfileBuilder
from .questionnaire import build_session_questionnaire, session_questionnaire


logger = logging.getLogger("andromeda.proftest.session")
MAX_SESSION_INTERACTIONS = 38


class ProftestSessionService:
    """Keep session transitions typed and outside FastAPI/ORM boundaries."""

    def __init__(
        self,
        catalog: ProftestCatalogService,
        recommendations: RecommendationServicePort,
        sessions: ProftestAnswerSessionRepository,
        analytics: ProftestAnalyticsWriter | None = None,
        *,
        profile_reader: CurrentUserProfileReader | None = None,
        ttl_seconds: int = 60 * 60 * 24 * 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self._catalog = catalog
        self._recommendations = recommendations
        self._sessions = sessions
        self._analytics = analytics
        self._profile_reader = profile_reader
        self._ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._profile_builder = UserProfileBuilder()
        self._selector = AdaptiveQuestionSelector()
        self._v3_selector = AdaptiveQuestionSelector(
            max_adaptive_questions=MAX_ADAPTIVE_QUESTIONS_V3,
            min_answers_before_stop=MIN_ADAPTIVE_ANSWERS_BEFORE_STOP_V3,
            stability_score_delta=TOP_THREE_SCORE_DELTA_V3,
        )
        self._factory = AdaptiveQuestionFactory()

    def start(self, scope: ProfileScope) -> ProftestSessionView:
        questionnaire = build_session_questionnaire()
        session = self._sessions.start(
            scope,
            question_set_version=questionnaire.question_set_version,
            current_question_id=questionnaire.questions[0].id,
            expires_at=self._expires_at(),
        )
        view = self._view(session)
        self._track(scope, session, AnalyticsEventType.TEST_STARTED)
        logger.info("proftest_session_start_complete status=%s revision=%d", session.status.value, session.revision)
        return view

    def current(self, scope: ProfileScope) -> ProftestSessionView:
        session = self._sessions.get_current(scope)
        if session is None:
            raise NotFoundError("Current proftest session was not found")
        profile_revision = self._profile_revision(scope) if session.status is SessionStatus.COMPLETED else None
        return self._view(session, profile_revision=profile_revision)

    def save(self, scope: ProfileScope, answers: tuple[SessionAnswer, ...], *, expected_revision: int) -> ProftestSessionView:
        session = self._require_draft(scope)
        updated = self._apply_answers(session, answers, advance=False)
        saved = self._sessions.save(scope, updated, expected_revision=expected_revision)
        return self._view(saved)

    def next(self, scope: ProfileScope, answer: SessionAnswer, *, expected_revision: int) -> ProftestSessionView:
        session = self._require_draft(scope)
        updated = self._apply_answers(session, (answer,), advance=True)
        saved = self._sessions.save(scope, updated, expected_revision=expected_revision)
        self._track(scope, saved, AnalyticsEventType.ANSWER_SELECTED, payload={"questionId": answer.question_id})
        return self._view(saved)

    def complete(self, scope: ProfileScope) -> ProftestSessionView:
        session = self._sessions.get_current(scope)
        if session is None:
            raise NotFoundError("Current proftest session was not found")
        questionnaire = self._questionnaire(session)
        if session.status is SessionStatus.COMPLETED:
            profile = self._profile_builder.build(session.answer_set, questionnaire.questions, self._adaptive_questions(session))
            profile_revision = self._profile_revision(scope)
            results = self._try_results(
                profile,
                profile_revision=profile_revision,
                question_set_version=session.question_set_version,
            )
            return ProftestSessionView(
                session=session,
                progress=self._progress(session, None, questionnaire),
                results=results,
                profile_revision=profile_revision,
            )
        self._validate_required(session.answer_set, questionnaire.questions)
        profile = self._profile_builder.build(session.answer_set, questionnaire.questions, self._adaptive_questions(session))
        completed, snapshot = self._sessions.complete(scope, session, profile, expires_at=self._expires_at())
        self._track(scope, completed, AnalyticsEventType.TEST_COMPLETED)
        results = self._try_results(
            profile,
            profile_revision=snapshot.revision,
            question_set_version=completed.question_set_version,
        )
        logger.info(
            "proftest_session_complete recommendations=%d profile_revision=%d recommendation_status=%s",
            len(results.recommendations) if results is not None else 0,
            snapshot.revision,
            "available" if results is not None else "unavailable",
        )
        return ProftestSessionView(
            session=completed,
            progress=self._progress(completed, None, questionnaire),
            results=results,
            profile_revision=snapshot.revision,
        )

    def append_analytics(self, scope: ProfileScope, events: tuple[ProftestAnalyticsEvent, ...]) -> int:
        if self._analytics is None:
            raise ValidationError("Proftest analytics is not configured")
        if len(events) > 50:
            raise ValidationError("Analytics batch is limited to 50 events")
        accepted = self._analytics.append(scope, events)
        logger.info("proftest_analytics_complete accepted=%d requested=%d", accepted, len(events))
        return accepted

    def _require_draft(self, scope: ProfileScope) -> ProftestAnswerSession:
        session = self._sessions.get_current(scope)
        if session is None:
            raise NotFoundError("Current proftest session was not found")
        if session.status is not SessionStatus.DRAFT:
            raise ConflictError("Proftest session is not editable")
        return session

    def _apply_answers(self, session: ProftestAnswerSession, inputs: tuple[SessionAnswer, ...], *, advance: bool) -> ProftestAnswerSession:
        if not inputs:
            raise ValidationError("At least one answer is required")
        questionnaire = self._questionnaire(session)
        core = questionnaire.questions
        core_map = {question.id: question for question in core}
        # Ranking the entire catalogue is only needed once the core questions
        # are complete (or when an adaptive branch is being edited). Keeping
        # core transitions cheap is important for browser UX and repeatable
        # ingestion-backed smoke tests.
        needs_selection = session.cursor >= len(core) or bool(session.answer_set.adaptive_answers) or any(item.question_id not in core_map for item in inputs)
        selection = self._selection(session, core) if needs_selection else None
        adaptive_questions = session.adaptive_questions
        if selection is not None:
            current_adaptive = self._current_question(session, core, selection)
            if current_adaptive is not None and current_adaptive.id not in {question.id for question in adaptive_questions}:
                adaptive_questions = (*adaptive_questions, current_adaptive)
        question_map = {**core_map, **{question.id: question for question in adaptive_questions}}
        answers = list(session.answer_set.answers)
        adaptive_answers = list(session.answer_set.adaptive_answers)
        changed = 0
        first_edited_index: int | None = None
        stale_ids = list(session.stale_question_ids)
        for incoming in inputs:
            question = question_map.get(incoming.question_id)
            if question is None:
                raise ValidationError("Question does not belong to the pinned question set or branch")
            if question.adaptive:
                if incoming.status.value != "answered" or len(incoming.option_ids) != 1:
                    raise ValidationError("Adaptive questions require one selected option")
                if incoming.option_ids[0] not in {option.id for option in question.options}:
                    logger.warning("[FIX:session-validation] rejected adaptive option question_id=%s", _safe_id(question.id))
                    raise ValidationError("Adaptive answer option does not belong to the selected question")
                dimension = incoming.dimension or (question.declared_dimensions[0] if question.declared_dimensions else None)
                if dimension not in question.declared_dimensions:
                    raise ValidationError("Adaptive answer dimension is not supported by the selected question")
                adaptive_answer = AdaptiveAnswer(question_id=question.id, option_id=incoming.option_ids[0], dimension=dimension)
                adaptive_old = next((item for item in adaptive_answers if item.question_id == adaptive_answer.question_id), None)
                if adaptive_old != adaptive_answer:
                    changed += 1
                adaptive_answers = [item for item in adaptive_answers if item.question_id != adaptive_answer.question_id]
                adaptive_answers.append(adaptive_answer)
                continue
            if incoming.status is AnswerStatus.SKIPPED and not question.allow_skip:
                raise ValidationError("Question does not allow skipping")
            if incoming.status is AnswerStatus.UNCERTAIN and not question.allow_uncertain:
                raise ValidationError("Question does not allow uncertain answers")
            if len(incoming.option_ids) != len(set(incoming.option_ids)):
                raise ValidationError("Answer options must be unique")
            if incoming.status is AnswerStatus.ANSWERED and not incoming.option_ids:
                raise ValidationError("Answered questions require at least one option")
            if incoming.status is AnswerStatus.SKIPPED and incoming.option_ids:
                raise ValidationError("Skipped questions cannot contain options")
            invalid_option_ids = set(incoming.option_ids) - {option.id for option in question.options}
            if invalid_option_ids:
                logger.warning("[FIX:session-validation] rejected option question_id=%s invalid_count=%d", _safe_id(question.id), len(invalid_option_ids))
                raise ValidationError("Answer option does not belong to the selected question")
            core_answer = incoming.to_answer()
            if len(core_answer.option_ids) > question.max_selected:
                raise ValidationError("Too many selected options")
            core_old = next((item for item in answers if item.question_id == core_answer.question_id), None)
            if core_old != core_answer:
                changed += 1
            answers = [item for item in answers if item.question_id != core_answer.question_id]
            answers.append(core_answer)
            answer_index = core.index(question)
            if core_old is not None and core_old != core_answer and answer_index < session.cursor:
                first_edited_index = answer_index if first_edited_index is None else min(first_edited_index, answer_index)

        if first_edited_index is not None and adaptive_answers:
            stale_ids.extend(item.question_id for item in adaptive_answers)
            adaptive_answers = []
            adaptive_questions = ()
        cursor = session.cursor
        if advance:
            last_core_index = max((core.index(core_map[item.question_id]) for item in inputs if item.question_id in core_map), default=-1)
            cursor = max(cursor, last_core_index + 1)
            if any(item.question_id not in core_map for item in inputs):
                cursor = max(cursor, len(core) + len(adaptive_answers))
        elif first_edited_index is not None:
            cursor = first_edited_index + 1
        updated = session.model_copy(
            update={
                "answer_set": AnswerSet(answers=tuple(sorted(answers, key=lambda item: item.question_id)), adaptive_answers=tuple(sorted(adaptive_answers, key=lambda item: item.question_id))),
                "adaptive_questions": adaptive_questions,
                "adaptive_state": None if first_edited_index is not None else session.adaptive_state,
                "cursor": cursor,
                "interaction_count": min(MAX_SESSION_INTERACTIONS, session.interaction_count + changed),
                "stale_question_ids": tuple(dict.fromkeys(stale_ids)),
            }
        )
        if first_edited_index is None and (self._core_is_complete(updated, core) or updated.answer_set.adaptive_answers):
            updated = self._refresh_adaptive_state(updated, questionnaire)
        logger.debug("proftest_session_answers_applied changed=%d cursor=%d adaptive=%d", changed, updated.cursor, len(updated.answer_set.adaptive_answers))
        return updated

    def _view(self, session: ProftestAnswerSession, *, profile_revision: int | None = None) -> ProftestSessionView:
        questionnaire = self._questionnaire(session)
        if session.status is SessionStatus.COMPLETED:
            profile = self._profile_builder.build(session.answer_set, questionnaire.questions, self._adaptive_questions(session))
            return ProftestSessionView(
                session=session,
                progress=self._progress(session, None, questionnaire),
                results=self._try_results(
                    profile,
                    profile_revision=profile_revision,
                    question_set_version=session.question_set_version,
                ),
                profile_revision=profile_revision,
            )
        if session.cursor < len(questionnaire.questions) or not self._core_is_complete(session, questionnaire.questions):
            core_index = self._next_core_index(session, questionnaire.questions)
            core_question = questionnaire.questions[core_index]
            return ProftestSessionView(session=session, current_question=core_question, progress=self._progress(session, core_question, questionnaire))
        selection = self._selection(session, questionnaire.questions)
        question = self._current_question(session, questionnaire.questions, selection)
        preliminary = self._preliminary(session, questionnaire.questions, selection)
        if selection.status.value == "skipped":
            logger.info("proftest_adaptive_stop reason=%s adaptive_count=%d", selection.stop_reason.value if selection.stop_reason else "unknown", selection.adaptive_count)
        logger.debug("proftest_session_view version=%s cursor=%d core=%d adaptive=%d topics=%d", session.question_set_version, session.cursor, len(questionnaire.questions), len(session.answer_set.adaptive_answers), len(preliminary.topics))
        return ProftestSessionView(session=session, current_question=question, progress=self._progress(session, question, questionnaire), adaptive=selection, preliminary=preliminary)

    def _profile_revision(self, scope: ProfileScope) -> int | None:
        if self._profile_reader is None:
            return None
        snapshot = self._profile_reader.get_current(scope)
        return snapshot.revision if snapshot is not None else None

    def _current_question(self, session: ProftestAnswerSession, core: tuple[Question, ...], selection: AdaptiveSelection) -> Question | None:
        if session.cursor < len(core):
            return core[session.cursor]
        if len(session.answer_set.adaptive_answers) >= self._max_adaptive_questions(session) or selection.status.value != "ready":
            return None
        return self._factory.create(selection, sequence=len(session.answer_set.adaptive_answers))

    def _selection(self, session: ProftestAnswerSession, core: tuple[Question, ...]) -> AdaptiveSelection:
        profile = self._profile_builder.build(session.answer_set, core, session.adaptive_questions)
        ranked = self._rank(profile)
        state = session.adaptive_state
        asked_dimensions = tuple(
            dimension
            for question in session.adaptive_questions
            if question.id in {item.question_id for item in session.answer_set.adaptive_answers}
            for dimension in question.declared_dimensions
        )
        selector = self._selector_for(session)
        selection = selector.select(
            tuple(AdaptiveCandidate(fingerprint=item.fingerprint, score=Decimal(item.score.content_fit)) for item in ranked),
            profile,
            asked_question_ids=tuple(item.question_id for item in session.answer_set.adaptive_answers),
            asked_dimensions=tuple(sorted(set(asked_dimensions))),
            adaptive_count=len(session.answer_set.adaptive_answers),
            ranking_snapshots=state.ranking_snapshots if state is not None else (),
            ranking_score_snapshots=state.ranking_score_snapshots if state is not None else (),
        )
        logger.debug("[FIX:adaptive] ranking_rebuilt adaptive_count=%d profile_dimensions=%d", len(session.answer_set.adaptive_answers), len(profile.confidence_by_dimension))
        return selection

    def _rank(self, profile: UserProfile) -> tuple[RankedFingerprint, ...]:
        fingerprints = self._catalog.list_fingerprints()
        if not fingerprints:
            logger.warning("proftest_adaptive_selection source_gap=empty_catalog")
            return ()
        return self._recommendations.rank_fingerprints(profile, fingerprints, limit=max(1, len(fingerprints)))

    def _refresh_adaptive_state(self, session: ProftestAnswerSession, questionnaire: Questionnaire) -> ProftestAnswerSession:
        # The repository stores this bounded typed state inside the existing JSON
        # boundary; no schema migration is required for old rows.
        questions = questionnaire.questions
        profile = self._profile_builder.build(session.answer_set, questions, session.adaptive_questions)
        ranked = self._rank(profile)
        top = ranked[:10]
        snapshot = tuple(item.fingerprint.program_id for item in top)
        score_snapshot = tuple(item.score.content_fit for item in top)
        previous = session.adaptive_state
        snapshots = (*previous.ranking_snapshots, snapshot) if previous is not None else (snapshot,)
        score_snapshots = (*previous.ranking_score_snapshots, score_snapshot) if previous is not None else (score_snapshot,)
        state = AdaptiveState(
            candidate_ids=snapshot,
            candidate_count=len(ranked),
            asked_question_ids=tuple(item.question_id for item in session.answer_set.adaptive_answers),
            uncertain_dimensions=(),
            ranking_snapshots=snapshots[-10:],
            ranking_score_snapshots=score_snapshots[-10:],
            adaptive_count=len(session.answer_set.adaptive_answers),
            stop_reason=None,
        )
        return session.model_copy(update={"adaptive_state": state})

    def _preliminary(self, session: ProftestAnswerSession, core: tuple[Question, ...], selection: AdaptiveSelection) -> PreliminaryProfile:
        profile = self._profile_builder.build(session.answer_set, core, session.adaptive_questions)
        topics = tuple(
            PreliminaryTopic(code=f"area:{area.value}", label=area_definition(area).name)
            for area, _weight in sorted(profile.preferred_subject_weights.items(), key=lambda item: (-item[1], item[0].value))[:3]
        )
        if not topics:
            topics = tuple(
                PreliminaryTopic(code=dimension.code, label=dimension.label)
                for dimension in selection.dimensions[:3]
            )
        return PreliminaryProfile(topics=topics)

    def _adaptive_questions(self, session: ProftestAnswerSession) -> tuple[Question, ...]:
        if session.adaptive_questions:
            return session.adaptive_questions
        if not session.answer_set.adaptive_answers:
            return ()
        # Compatibility for drafts created before adaptive question snapshots
        # were persisted. New sessions always take the snapshot path above.
        questionnaire = self._questionnaire(session)
        base_session = session.model_copy(update={"answer_set": AnswerSet(answers=session.answer_set.answers)})
        selection = self._selection(base_session, questionnaire.questions)
        logger.warning("[FIX:adaptive] rebuilding_legacy_question_snapshots adaptive_count=%d", len(session.answer_set.adaptive_answers))
        return self._adaptive_questions_for_selection(selection, len(session.answer_set.adaptive_answers))

    def _adaptive_questions_for_selection(self, selection: AdaptiveSelection | None, count: int) -> tuple[Question, ...]:
        if selection is None:
            return ()
        return tuple(question for index in range(count) if (question := self._factory.create(selection, sequence=index)) is not None)

    def _results(
        self,
        profile: UserProfile,
        *,
        profile_revision: int | None = None,
        question_set_version: str | None = None,
    ) -> ProftestResults:
        fingerprints = self._catalog.list_fingerprints()
        result = self._recommendations.recommend_from_fingerprints(
            RecommendationRequest(profile=profile, limit=10),
            fingerprints,
            profile_revision=profile_revision,
            question_set_version=question_set_version,
        )
        return ProftestResults(profile=profile, recommendations=result.recommendations)

    def _try_results(
        self,
        profile: UserProfile,
        *,
        profile_revision: int | None,
        question_set_version: str,
    ) -> ProftestResults | None:
        try:
            return self._results(
                profile,
                profile_revision=profile_revision,
                question_set_version=question_set_version,
            )
        except Exception:
            logger.exception(
                "proftest_recommendations_unavailable profile_saved=True profile_revision=%s question_set_version=%s",
                profile_revision if profile_revision is not None else "unknown",
                question_set_version,
            )
            return None

    @staticmethod
    def _validate_required(answer_set: AnswerSet, questions: tuple[Question, ...]) -> None:
        answers = {answer.question_id: answer for answer in answer_set.answers}
        missing = [question.id for question in questions if question.required and question.id not in answers]
        skipped = [question.id for question in questions if answers.get(question.id) is not None and answers[question.id].status.value == "skipped" and question.required]
        if missing or skipped:
            raise ValidationError("Required proftest questions are incomplete")

    @staticmethod
    def _core_is_complete(session: ProftestAnswerSession, questions: tuple[Question, ...]) -> bool:
        answers = {answer.question_id: answer for answer in session.answer_set.answers}
        return all(
            question.id in answers and answers[question.id].status in {AnswerStatus.ANSWERED, AnswerStatus.UNCERTAIN}
            for question in questions
            if question.required
        )

    @staticmethod
    def _next_core_index(session: ProftestAnswerSession, questions: tuple[Question, ...]) -> int:
        answers = {answer.question_id: answer for answer in session.answer_set.answers}
        for index, question in enumerate(questions):
            answer = answers.get(question.id)
            if question.required and (answer is None or answer.status not in {AnswerStatus.ANSWERED, AnswerStatus.UNCERTAIN}):
                return index
        return min(session.cursor, len(questions) - 1)

    def _questionnaire(self, session: ProftestAnswerSession) -> Questionnaire:
        try:
            return session_questionnaire(session.question_set_version)
        except ValueError as exc:
            logger.error("proftest_session_invalid_question_set version=%s", _safe_id(session.question_set_version))
            raise ValidationError("Proftest session question set is not supported") from exc

    @staticmethod
    def _max_adaptive_questions(session: ProftestAnswerSession) -> int:
        return MAX_ADAPTIVE_QUESTIONS_V3 if session.question_set_version == "proftest-v3" else MAX_ADAPTIVE_QUESTIONS_V2

    def _selector_for(self, session: ProftestAnswerSession) -> AdaptiveQuestionSelector:
        return self._v3_selector if session.question_set_version == "proftest-v3" else self._selector

    def _progress(self, session: ProftestAnswerSession, question: Question | None, questionnaire: Questionnaire) -> SessionProgress:
        core_count = len(questionnaire.questions)
        stages = (QuestionStage.ABOUT.value, QuestionStage.INTERESTS.value, QuestionStage.WORK_STYLE.value, QuestionStage.ANTI_INTERESTS.value, QuestionStage.TRADE_OFFS.value, QuestionStage.CLARIFICATION.value)
        stage = question.stage.value if question is not None and question.stage is not None else QuestionStage.CLARIFICATION.value
        stage_index = stages.index(stage)
        core_remaining = max(0, core_count - min(session.cursor, core_count))
        max_adaptive = self._max_adaptive_questions(session)
        adaptive_remaining = 0 if session.status is SessionStatus.COMPLETED or (session.cursor >= core_count and question is None) else max(0, max_adaptive - len(session.answer_set.adaptive_answers))
        return SessionProgress(stage=stage, stage_index=stage_index, stage_count=len(stages), answer_count=session.interaction_count, min_remaining=core_remaining + adaptive_remaining, max_remaining=min(MAX_SESSION_INTERACTIONS, core_remaining + max_adaptive))

    def _track(self, scope: ProfileScope, session: ProftestAnswerSession, event_type: AnalyticsEventType, *, payload: dict[str, str | int | float | bool | None] | None = None) -> None:
        if self._analytics is None:
            return
        now = self._clock()
        event = ProftestAnalyticsEvent(
            event_id=f"proftest-event:{__import__('uuid').uuid4().hex}",
            session_id=session.session_id,
            question_set_version=session.question_set_version,
            event_type=event_type,
            payload=payload or {},
            occurred_at=now,
            expires_at=now + timedelta(days=180),
        )
        self._analytics.append(scope, (event,))

    def _expires_at(self) -> datetime:
        return self._clock() + timedelta(seconds=self._ttl_seconds)


def _safe_id(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")[:128]


__all__ = ["ProftestSessionService"]
