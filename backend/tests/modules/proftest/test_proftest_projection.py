from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import cast

from andromeda.modules.proftest.contracts.public import (
    Answer,
    AnswerSet,
    ProfileScope,
    ProftestAnswerSession,
    ProgramFingerprint,
    SessionStatus,
    UserProfile,
    UserProfileSnapshot,
)
from andromeda.modules.proftest.services.questionnaire import build_session_questionnaire
from andromeda.modules.proftest.repository.ports import ProftestAnswerSessionRepository
from andromeda.modules.proftest.services.catalog import ProftestCatalogService
from andromeda.modules.proftest.services.session import ProftestSessionService
from andromeda.modules.recommendations.contracts.public import RankedFingerprint, RecommendationRequest, RecommendationResult, RecommendationServicePort


class _Catalog:
    def list_fingerprints(self) -> tuple[ProgramFingerprint, ...]:
        return ()


class _Recommendations:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[int | None, str | None]] = []

    def rank_fingerprints(
        self,
        profile: UserProfile,
        fingerprints: Iterable[ProgramFingerprint],
        *,
        limit: int | None = None,
    ) -> tuple[RankedFingerprint, ...]:
        return ()

    def recommend_from_fingerprints(
        self,
        request: RecommendationRequest,
        fingerprints: Iterable[ProgramFingerprint],
        *,
        profile_revision: int | None = None,
        question_set_version: str | None = None,
    ) -> RecommendationResult:
        self.calls.append((profile_revision, question_set_version))
        if self.fail:
            raise RuntimeError("catalog projection unavailable")
        return RecommendationResult(profile=request.profile, recommendations=())


class _Store:
    def __init__(self, session: ProftestAnswerSession) -> None:
        self.current = session

    def get_current(self, scope: ProfileScope) -> ProftestAnswerSession:
        return self.current

    def complete(self, scope: ProfileScope, session: ProftestAnswerSession, profile: UserProfile, *, expires_at: datetime) -> tuple[ProftestAnswerSession, UserProfileSnapshot]:
        now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
        self.current = session.model_copy(update={"status": SessionStatus.COMPLETED, "current_question_id": None, "updated_at": now, "expires_at": expires_at})
        snapshot = UserProfileSnapshot(
            profile_id="profile:" + "b" * 32,
            profile=profile,
            revision=7,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        return self.current, snapshot


def _draft_session() -> ProftestAnswerSession:
    questionnaire = build_session_questionnaire()
    answers = tuple(Answer(question_id=question.id, option_ids=(question.options[0].id,)) for question in questionnaire.questions)
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    return ProftestAnswerSession(
        session_id="proftest-session:" + "a" * 32,
        question_set_version=questionnaire.question_set_version,
        answer_set=AnswerSet(answers=answers),
        cursor=len(questionnaire.questions),
        interaction_count=len(questionnaire.questions),
        revision=3,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(days=1),
    )


def _service(recommendations: _Recommendations) -> ProftestSessionService:
    return ProftestSessionService(
        cast(ProftestCatalogService, _Catalog()),
        cast(RecommendationServicePort, recommendations),
        cast(ProftestAnswerSessionRepository, _Store(_draft_session())),
    )


def test_completion_projects_persisted_profile_context_into_recommendations() -> None:
    recommendations = _Recommendations()
    view = _service(recommendations).complete(ProfileScope(session_key_hash="c" * 64))

    assert view.session.status is SessionStatus.COMPLETED
    assert view.profile_revision == 7
    assert view.results is not None
    assert recommendations.calls == [(7, "proftest-v3")]


def test_completion_keeps_saved_profile_visible_when_recommendations_fail() -> None:
    recommendations = _Recommendations(fail=True)
    view = _service(recommendations).complete(ProfileScope(session_key_hash="d" * 64))

    assert view.session.status is SessionStatus.COMPLETED
    assert view.profile_revision == 7
    assert view.results is None
    assert recommendations.calls == [(7, "proftest-v3")]
