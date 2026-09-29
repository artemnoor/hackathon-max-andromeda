from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import ProftestAnswerSessionModel
from andromeda.infrastructure.repositories.proftest_sessions import SqlAlchemyProftestSessionRepository
from andromeda.modules.proftest.contracts.public import AdaptiveState, AnalyticsEventType, ProfileScope, ProftestAnalyticsEvent, Question, QuestionBlock, SessionStatus


def _event(*, event_type: AnalyticsEventType, payload: dict[str, object], expires_at: datetime) -> ProftestAnalyticsEvent:
    now = datetime.now(timezone.utc)
    return ProftestAnalyticsEvent(
        event_id=f"proftest-event:{uuid4().hex}",
        question_set_version="proftest-v2",
        event_type=event_type,
        payload=payload,
        occurred_at=now,
        expires_at=expires_at,
    )


def test_analytics_aggregates_are_deduplicated_and_do_not_double_count_metrics(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'proftest-analytics.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="a" * 64)
    now = datetime.now(timezone.utc)
    events = (
        _event(event_type=AnalyticsEventType.TEST_STARTED, payload={}, expires_at=now + timedelta(days=1)),
        _event(event_type=AnalyticsEventType.ANSWER_SELECTED, payload={"durationMs": 100, "uncertainty": True, "changed": True}, expires_at=now + timedelta(days=1)),
        _event(event_type=AnalyticsEventType.TEST_COMPLETED, payload={"durationMs": 300, "adaptiveCount": 2}, expires_at=now + timedelta(days=1)),
    )

    with Session(engine) as database_session:
        repository = SqlAlchemyProftestSessionRepository(database_session)
        assert repository.append(scope, events) == 3
        assert repository.append(scope, events) == 0

        aggregates = repository.aggregates(question_set_version="proftest-v2")

    assert aggregates["total_events"] == 3
    assert aggregates["test_started"] == 1
    assert aggregates["test_completed"] == 1
    assert aggregates["uncertain_answers"] == 1
    assert aggregates["changed_answers"] == 1
    assert aggregates["adaptive_questions"] == 1
    assert aggregates["response_time_median_ms"] == 200.0
    assert aggregates["completion_rate"] == 1.0


def test_analytics_retention_purges_expired_rows_on_next_write(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'proftest-retention.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="b" * 64)
    now = datetime.now(timezone.utc)
    expired = _event(event_type=AnalyticsEventType.STAGE_VIEWED, payload={}, expires_at=now - timedelta(seconds=1))
    current = _event(event_type=AnalyticsEventType.STAGE_VIEWED, payload={}, expires_at=now + timedelta(days=1))

    with Session(engine) as database_session:
        repository = SqlAlchemyProftestSessionRepository(database_session)
        assert repository.append(scope, (expired,)) == 1
        assert repository.append(scope, (current,)) == 1
        aggregates = repository.aggregates(question_set_version="proftest-v2")

    assert aggregates["total_events"] == 1
    assert aggregates["stage_viewed"] == 1


def test_adaptive_question_snapshots_survive_session_round_trip(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'proftest-session-state.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="c" * 64)
    now = datetime.now(timezone.utc)
    question = Question(
        id="adaptive_0_area_math_area_data",
        block=QuestionBlock.ADAPTIVE,
        prompt="Выбор",
        options=(
            {"id": "first", "label": "Первое"},
            {"id": "second", "label": "Второе"},
        ),
        adaptive=True,
        declared_dimensions=("area:mathematics_statistics", "area:computer_science_data"),
    )

    with Session(engine) as database_session:
        repository = SqlAlchemyProftestSessionRepository(database_session)
        started = repository.start(
            scope,
            question_set_version="proftest-v2",
            current_question_id="context_goal",
            expires_at=now + timedelta(days=1),
        )
        updated = started.model_copy(
            update={
                "adaptive_questions": (question,),
                "adaptive_state": AdaptiveState(
                    candidate_ids=("program:09.03.01-01",),
                    candidate_count=1,
                    ranking_snapshots=(("program:09.03.01-01",),),
                    ranking_score_snapshots=((80,),),
                    adaptive_count=0,
                ),
            }
        )
        repository.save(scope, updated, expected_revision=started.revision)
        resumed = repository.get_current(scope)

    assert resumed is not None
    assert resumed.adaptive_questions == (question,)
    assert resumed.adaptive_state is not None
    assert resumed.adaptive_state.ranking_score_snapshots == ((80,),)


def test_expired_draft_is_not_resumed_and_next_start_creates_a_new_session(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'proftest-expiry.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="d" * 64)
    now = datetime.now(timezone.utc)

    with Session(engine) as database_session:
        repository = SqlAlchemyProftestSessionRepository(database_session)
        expired = repository.start(
            scope,
            question_set_version="proftest-v3",
            current_question_id="core_doing",
            expires_at=now + timedelta(days=1),
        )
        database_session.execute(update(ProftestAnswerSessionModel).where(ProftestAnswerSessionModel.session_id == expired.session_id).values(updated_at=now - timedelta(seconds=2), expires_at=now - timedelta(seconds=1)))
        database_session.commit()
        assert repository.get_current(scope) is None
        replacement = repository.start(
            scope,
            question_set_version="proftest-v3",
            current_question_id="core_doing",
            expires_at=now + timedelta(days=1),
        )

    assert expired.status is SessionStatus.DRAFT
    assert replacement.session_id != expired.session_id
    assert replacement.status is SessionStatus.DRAFT
