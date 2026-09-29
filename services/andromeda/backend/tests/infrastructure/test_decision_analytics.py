from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.base import Base
from andromeda.infrastructure.database.models import DecisionAnalyticsEventModel
from andromeda.infrastructure.repositories.decision_analytics import SqlAlchemyDecisionAnalyticsRepository
from andromeda.modules.decision.contracts.public import (
    DecisionAnalyticsAction,
    DecisionAnalyticsEvent,
    DecisionAnalyticsEventType,
    DecisionAnalyticsPayload,
    DecisionAnalyticsSource,
)
from andromeda.modules.proftest.contracts.public import ProfileScope


NOW = datetime.now(timezone.utc)


def _event(event_id: str, *, occurred_at: datetime = NOW, expires_at: datetime | None = None) -> DecisionAnalyticsEvent:
    return DecisionAnalyticsEvent(
        event_id=event_id,
        event_type=DecisionAnalyticsEventType.SESSION_STARTED,
        payload=DecisionAnalyticsPayload(source=DecisionAnalyticsSource.SYSTEM, action=DecisionAnalyticsAction.START),
        occurred_at=occurred_at,
        expires_at=expires_at or (occurred_at + timedelta(days=30)),
    )


def _typed_event(event_id: str, event_type: DecisionAnalyticsEventType, payload: DecisionAnalyticsPayload) -> DecisionAnalyticsEvent:
    return DecisionAnalyticsEvent(
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        occurred_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )


def test_repository_is_idempotent_per_owner_and_purges_expired_rows(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'decision-analytics.db').as_posix()}")
    Base.metadata.create_all(engine)
    anonymous = ProfileScope(session_key_hash="a" * 64)
    account = ProfileScope(session_key_hash="b" * 64, account_id="account:" + "c" * 32)
    event_id = "decision-event:" + "a" * 32
    try:
        with Session(engine) as session:
            repository = SqlAlchemyDecisionAnalyticsRepository(session)
            assert repository.append(anonymous, (_event(event_id),)) == 1
            assert repository.append(anonymous, (_event(event_id),)) == 0
            assert repository.append(account, (_event(event_id),)) == 1

            expired_id = "decision-event:" + "b" * 32
            expired_at = NOW - timedelta(days=1)
            assert repository.append(
                anonymous,
                (_event(expired_id, occurred_at=NOW - timedelta(days=2), expires_at=expired_at),),
            ) == 0
            assert session.scalar(
                select(DecisionAnalyticsEventModel).where(DecisionAnalyticsEventModel.event_id == expired_id)
            ) is None

            rows = session.scalars(select(DecisionAnalyticsEventModel)).all()
            assert len(rows) == 2
            assert {row.owner_key for row in rows} == {anonymous.owner_key, account.owner_key}
            assert all("email" not in row.payload_json and "score" not in row.payload_json for row in rows)
    finally:
        engine.dispose()


def test_funnel_is_distinct_owner_aggregate_and_never_exposes_payloads(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'decision-funnel.db').as_posix()}")
    Base.metadata.create_all(engine)
    anonymous = ProfileScope(session_key_hash="d" * 64)
    account = ProfileScope(session_key_hash="e" * 64, account_id="account:" + "f" * 32)
    program = "program:bmstu:09.03.01-101"
    try:
        with Session(engine) as session:
            repository = SqlAlchemyDecisionAnalyticsRepository(session)
            repository.append(
                anonymous,
                (
                    _event("decision-event:" + "1" * 32),
                    _typed_event("decision-event:" + "2" * 32, DecisionAnalyticsEventType.PROGRAM_ADDED, DecisionAnalyticsPayload(program_id=program)),
                    _typed_event("decision-event:" + "3" * 32, DecisionAnalyticsEventType.SHORTLIST_SIZE_CHANGED, DecisionAnalyticsPayload(program_id=program, shortlist_size_before=0, shortlist_size_after=1)),
                    _typed_event("decision-event:" + "4" * 32, DecisionAnalyticsEventType.FINAL_CHOICE_SELECTED, DecisionAnalyticsPayload(program_id=program)),
                ),
            )
            repository.append(
                account,
                (
                    _event("decision-event:" + "5" * 32),
                    _typed_event("decision-event:" + "6" * 32, DecisionAnalyticsEventType.PROGRAM_ADDED, DecisionAnalyticsPayload(program_id=program)),
                ),
            )

            funnel = repository.funnel()

            assert funnel.decision_sessions == 2
            assert funnel.shortlist_started == 2
            assert funnel.final_choice_selected == 1
            assert funnel.average_shortlist_size == 1.0
            assert funnel.final_choice_conversion_percent == 50.0
    finally:
        engine.dispose()
