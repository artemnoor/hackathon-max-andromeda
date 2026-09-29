from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import QuerySessionModel
from andromeda.infrastructure.repositories.query_sessions import (
    SqlAlchemyQuerySessionRepository,
)
from andromeda.modules.admissions.contracts.public import FundingType
from andromeda.modules.conversation.contracts.public import (
    NextAction,
    PolicyQueryContext,
    PolicyQueryFocus,
    PolicyQueryYear,
    QuerySession,
)
from andromeda.modules.conversation.services.engine import ConversationEngine
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.shared.contracts.errors import ConflictError

NOW = datetime.now(UTC) - timedelta(minutes=1)


def _session(scope: ProfileScope) -> QuerySession:
    return QuerySession(
        session_id="query-session:" + "e" * 32,
        owner_scope=scope,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def test_query_session_repository_is_owner_bound_revisioned_and_bindable(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'query-sessions.db').as_posix()}")
    Base.metadata.create_all(engine)
    anonymous = ProfileScope(session_key_hash="f" * 64)
    other = ProfileScope(session_key_hash="0" * 64)
    try:
        with Session(engine) as database_session:
            repository = SqlAlchemyQuerySessionRepository(database_session)
            created = repository.save(_session(anonymous))
            assert repository.get(created.session_id, owner_scope=other) is None
            assert repository.get(created.session_id, owner_scope=anonymous) is not None

            updated = ConversationEngine().apply(created, "Куда я прохожу с 270?", now=NOW + timedelta(seconds=1))
            repository.save(updated, expected_revision=1)
            with pytest.raises(ConflictError):
                repository.save(updated, expected_revision=1)

            bound = repository.bind_anonymous_to_account(
                updated.session_id,
                anonymous_scope=anonymous,
                account_id="account:" + "1" * 32,
            )
            assert bound.owner_scope.account_id == "account:" + "1" * 32
            assert repository.get(bound.session_id, owner_scope=anonymous) is None
            assert repository.get(bound.session_id, owner_scope=bound.owner_scope) is not None
    finally:
        engine.dispose()


def test_query_session_repository_purges_expired_rows_with_a_bound(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'query-sessions-purge.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="a" * 64)
    expired = _session(scope).model_copy(
        update={
            "session_id": "query-session:" + "1" * 32,
            "expires_at": NOW - timedelta(seconds=1),
            "updated_at": NOW - timedelta(minutes=2),
        }
    )
    active = _session(scope).model_copy(update={"session_id": "query-session:" + "2" * 32})
    try:
        with Session(engine) as database_session:
            repository = SqlAlchemyQuerySessionRepository(database_session)
            repository.save(expired)
            repository.save(active)
            assert repository.purge_expired(now=NOW, limit=1) == 1
            assert repository.get(expired.session_id, owner_scope=scope) is None
            assert repository.get(active.session_id, owner_scope=scope) is not None
    finally:
        engine.dispose()


def test_admission_funding_fact_survives_query_session_json_round_trip(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'query-sessions-funding.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="c" * 64)
    try:
        with Session(engine) as database_session:
            repository = SqlAlchemyQuerySessionRepository(database_session)
            conversation = ConversationEngine()
            session = conversation.apply(
                _session(scope),
                "Куда я прохожу с 270: русский 90, математика 90, физика 90, university:bmstu",
                now=NOW + timedelta(seconds=1),
            )
            assert session.next_action is NextAction.ASK_FOR_FUNDING
            repository.save(session)

            restored = repository.get(session.session_id, owner_scope=scope)
            assert restored is not None
            funded = conversation.apply(
                restored,
                "бюджет",
                expected_revision=restored.revision,
                now=NOW + timedelta(seconds=2),
            )

            assert funded.next_action is NextAction.EXECUTE_QUERY
            assert funded.missing_slots == ()
            assert funded.known_slots["funding_type"] is FundingType.BUDGET
            assert funded.confirmed_parameters["funding_type"].value is FundingType.BUDGET
            repository.save(funded, expected_revision=restored.revision)

            funded_restored = repository.get(funded.session_id, owner_scope=scope)
            assert funded_restored is not None
            assert funded_restored.known_slots["funding_type"] is FundingType.BUDGET
            assert funded_restored.confirmed_parameters["funding_type"].value is FundingType.BUDGET
            changed = conversation.apply(
                funded_restored,
                "платное",
                expected_revision=funded_restored.revision,
                now=NOW + timedelta(seconds=3),
            )
            assert changed.next_action is NextAction.EXECUTE_QUERY
            assert changed.confirmed_parameters["funding_type"].value is FundingType.PAID
    finally:
        engine.dispose()


def test_policy_query_context_survives_query_session_json_round_trip(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'query-sessions-policy.db').as_posix()}")
    Base.metadata.create_all(engine)
    scope = ProfileScope(session_key_hash="d" * 64)
    context = PolicyQueryContext(
        focus=PolicyQueryFocus.APPLICABILITY,
        mentioned_effective_year=PolicyQueryYear(year=2028),
        as_known_at=NOW,
    )
    try:
        with Session(engine) as database_session:
            repository = SqlAlchemyQuerySessionRepository(database_session)
            query_session = _session(scope).model_copy(update={"policy_query_context": context})
            repository.save(query_session)

            restored = repository.get(query_session.session_id, owner_scope=scope)
            assert restored is not None
            assert restored.policy_query_context == context

            model = database_session.get(QuerySessionModel, query_session.session_id)
            assert model is not None
            legacy_state = dict(model.state_json)
            legacy_state.pop("policy_query_context")
            model.state_json = legacy_state
            database_session.commit()

            restored_legacy = repository.get(query_session.session_id, owner_scope=scope)
            assert restored_legacy is not None
            assert restored_legacy.policy_query_context is None
    finally:
        engine.dispose()
