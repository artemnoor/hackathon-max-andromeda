from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from andromeda.modules.conversation.contracts.public import (
    AdmissionUniversityScope,
    ConversationIntent,
    ExamScore,
    NextAction,
    QuerySession,
)
from andromeda.modules.conversation.services.query_compiler import compile_session
from andromeda.modules.entity_resolution.contracts.public import ResolutionEntityType
from andromeda.modules.proftest.contracts.public import ProfileScope


def test_catalog_wide_admission_is_split_into_bounded_requests_without_truncation() -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    program_ids = tuple(f"program:bmstu:09.03.01-{index:02d}" for index in range(1, 102))
    session = QuerySession(
        session_id="query-session:" + "a" * 32,
        owner_scope=ProfileScope(session_key_hash="b" * 64),
        intent=ConversationIntent.ADMISSION_SEARCH,
        admission_university_scope=AdmissionUniversityScope.ANY_UNIVERSITY,
        entities={ResolutionEntityType.PROGRAM: program_ids},
        known_slots={
            "exam_scores": (
                ExamScore(subject="русский язык", score=Decimal(90)),
                ExamScore(subject="математика", score=Decimal(90)),
                ExamScore(subject="информатика", score=Decimal(90)),
            )
        },
        next_action=NextAction.EXECUTE_QUERY,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
    )

    compilation = compile_session(session, candidate_program_ids=program_ids)

    assert compilation.admission_request is None
    assert tuple(len(request.program_ids) for request in compilation.admission_requests) == (50, 50, 1)
    assert tuple(program_id for request in compilation.admission_requests for program_id in request.program_ids) == program_ids
