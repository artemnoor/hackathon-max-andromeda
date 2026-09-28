from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError as PydanticValidationError

from andromeda.modules.decision.contracts.public import (
    DecisionAnalyticsAction,
    DecisionAnalyticsClientEvent,
    DecisionAnalyticsEventType,
    DecisionAnalyticsPayload,
    DecisionAnalyticsSource,
    DecisionAnalyticsStatus,
    ShortlistRole,
)
from andromeda.modules.decision.domain.entities import DecisionChoice, DecisionState
from andromeda.modules.decision.domain.values import DecisionSourceKind
from andromeda.modules.decision.services.analytics import DecisionAnalyticsService
from andromeda.modules.proftest.contracts.public import ProfileScope


NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
PROGRAM_A = "program:09.03.01-01"
PROGRAM_B = "program:09.03.01-02"
SCOPE = ProfileScope(session_key_hash="a" * 64)


class RecordingWriter:
    def __init__(self) -> None:
        self.events = []

    def append(self, scope: ProfileScope, events: tuple[object, ...]) -> int:
        del scope
        self.events.extend(events)
        return len(events)


class BrokenWriter:
    def append(self, scope: ProfileScope, events: tuple[object, ...]) -> int:
        del scope, events
        raise RuntimeError("analytics storage unavailable")


def test_allowlist_is_exact_and_payload_rejects_unknown_or_unsafe_shape() -> None:
    assert {event.value for event in DecisionAnalyticsEventType} == {
        "decision_session_started",
        "program_considered",
        "program_added_to_shortlist",
        "program_removed_from_shortlist",
        "program_restored",
        "program_marked_primary",
        "program_marked_alternative",
        "admission_constraints_added",
        "admission_fit_viewed",
        "comparison_started",
        "comparison_completed",
        "preference_question_answered",
        "system_suggestion_shown",
        "system_suggestion_accepted",
        "system_suggestion_rejected",
        "shortlist_size_changed",
        "shortlist_returned_to",
        "final_choice_selected",
        "final_choice_changed",
        "decision_reopened",
    }

    with pytest.raises(PydanticValidationError):
        DecisionAnalyticsPayload.model_validate({"source": "decision", "email": "private@example.test"})
    with pytest.raises(PydanticValidationError):
        DecisionAnalyticsPayload(program_ids=(PROGRAM_A, PROGRAM_A))
    with pytest.raises(PydanticValidationError):
        DecisionAnalyticsPayload(program_ids=(PROGRAM_A, PROGRAM_B, "program:09.03.01-03", "program:09.03.01-04"))


def test_event_contract_requires_only_bounded_identifiers_for_each_shape() -> None:
    with pytest.raises(PydanticValidationError):
        DecisionAnalyticsClientEvent(
            event_id="decision-event:" + "a" * 32,
            event_type=DecisionAnalyticsEventType.PROGRAM_ADDED,
        )
    with pytest.raises(PydanticValidationError):
        DecisionAnalyticsClientEvent(
            event_id="decision-event:" + "a" * 32,
            event_type=DecisionAnalyticsEventType.COMPARISON_STARTED,
            payload=DecisionAnalyticsPayload(program_ids=(PROGRAM_A,)),
        )
    event = DecisionAnalyticsClientEvent(
        event_id="decision-event:" + "b" * 32,
        event_type=DecisionAnalyticsEventType.PREFERENCE_QUESTION_ANSWERED,
        payload=DecisionAnalyticsPayload(
            source=DecisionAnalyticsSource.PROFTEST,
            action=DecisionAnalyticsAction.ANSWER,
            question_id="question_1",
            option_id="option_2",
        ),
    )
    assert event.payload.question_id == "question_1"


def test_mutation_events_use_authoritative_shortlist_sizes() -> None:
    writer = RecordingWriter()
    service = DecisionAnalyticsService(writer, clock=lambda: NOW)
    before = DecisionState(created_at=NOW, updated_at=NOW)
    after = before.with_choice(
        DecisionChoice().add_shortlist(PROGRAM_A, role=ShortlistRole.PRIMARY, origin=DecisionSourceKind.USER, now=NOW),
        now=NOW,
    )

    accepted = service.record_mutation(
        SCOPE,
        operation="add_shortlist",
        program_id=PROGRAM_A,
        before=before,
        after=after,
    )

    assert accepted == 2
    assert [event.event_type for event in writer.events] == [
        DecisionAnalyticsEventType.PROGRAM_ADDED,
        DecisionAnalyticsEventType.SHORTLIST_SIZE_CHANGED,
    ]
    size_event = writer.events[1]
    assert size_event.payload.shortlist_size_before == 0
    assert size_event.payload.shortlist_size_after == 1
    assert size_event.payload.program_id == PROGRAM_A


def test_storage_failure_is_observational_and_returns_ignored_count() -> None:
    service = DecisionAnalyticsService(BrokenWriter(), clock=lambda: NOW)
    state = DecisionState(created_at=NOW, updated_at=NOW)
    assert service.record_mutation(
        SCOPE,
        operation="mark_considered",
        program_id=PROGRAM_A,
        before=state,
        after=state.with_choice(state.choice.consider(PROGRAM_A), now=NOW),
    ) == 0
