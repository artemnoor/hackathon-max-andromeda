from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from andromeda.modules.conversation.contracts.public import (
    ConversationIntent,
    NextAction,
    QuerySession,
)
from andromeda.modules.conversation.services.engine import ConversationEngine
from andromeda.modules.conversation.services.query_compiler import compile_session
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.shared.contracts.errors import ConflictError

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _session() -> QuerySession:
    return QuerySession(
        session_id="query-session:" + "c" * 32,
        owner_scope=ProfileScope(session_key_hash="d" * 64),
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def test_admission_conversation_delegates_to_batch_admission_fit_contract() -> None:
    engine = ConversationEngine()
    session = engine.apply(_session(), "Куда я прохожу с 270?", now=NOW + timedelta(seconds=1))
    assert session.next_action is NextAction.ASK_FOR_EXAMS
    session = engine.apply(
        session,
        "русский 90, математика 90, информатика 90",
        expected_revision=session.revision,
        now=NOW + timedelta(seconds=2),
    )
    assert session.next_action is NextAction.ASK_FOR_UNIVERSITY_SCOPE
    session = engine.apply(
        session,
        "university:bmstu, бюджет",
        expected_revision=session.revision,
        now=NOW + timedelta(seconds=3),
    )
    assert session.next_action is NextAction.EXECUTE_QUERY

    compiled = compile_session(
        session,
        candidate_program_ids=("program:bmstu:09.03.01-02", "program:bmstu:09.03.01-12"),
    )
    assert compiled.admission_request is not None
    assert compiled.admission_request.program_ids == (
        "program:bmstu:09.03.01-02",
        "program:bmstu:09.03.01-12",
    )
    assert tuple(item.subject for item in compiled.admission_request.applicant.scores) == (
        "русский язык",
        "математика",
        "информатика",
    )


def test_analytics_conversation_compiles_into_one_typed_query_spec() -> None:
    session = ConversationEngine().apply(
        _session(),
        "Сравни program:bmstu:09.03.01-02 и program:bmstu:09.03.01-12 по математике и программированию",
        now=NOW + timedelta(seconds=1),
    )
    assert session.intent is ConversationIntent.COMPARE_PROGRAMS
    compiled = compile_session(session)
    assert compiled.analytics_query is not None
    assert compiled.analytics_query.scope.value == "program"
    assert compiled.analytics_query.scope_ids == (
        "program:bmstu:09.03.01-02",
        "program:bmstu:09.03.01-12",
    )
    assert compiled.analytics_query.metrics == ("math_share", "programming_share")


def test_conversation_revision_is_checked_at_engine_boundary() -> None:
    with pytest.raises(ConflictError):
        ConversationEngine().apply(_session(), "Куда я прохожу с 270?", expected_revision=99, now=NOW)
