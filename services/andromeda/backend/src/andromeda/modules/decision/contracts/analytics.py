"""Bounded, privacy-safe contracts for decision product analytics.

Analytics is deliberately an observational boundary.  These contracts contain
only canonical program identifiers and small enumerations/counts; profile
answers, admission scores, cookies and source bodies are not representable.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self, TypeAlias

from pydantic import Field, StringConstraints, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import ProgramId

from ..domain.values import ShortlistRole


DecisionAnalyticsEventId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^decision-event:[0-9a-f]{32}$"),
]
AnalyticsToken: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$"),
]


class DecisionAnalyticsEventType(StrEnum):
    """The only decision events that may be persisted."""

    SESSION_STARTED = "decision_session_started"
    PROGRAM_CONSIDERED = "program_considered"
    PROGRAM_ADDED = "program_added_to_shortlist"
    PROGRAM_REMOVED = "program_removed_from_shortlist"
    PROGRAM_RESTORED = "program_restored"
    PROGRAM_MARKED_PRIMARY = "program_marked_primary"
    PROGRAM_MARKED_ALTERNATIVE = "program_marked_alternative"
    ADMISSION_CONSTRAINTS_ADDED = "admission_constraints_added"
    ADMISSION_FIT_VIEWED = "admission_fit_viewed"
    COMPARISON_STARTED = "comparison_started"
    COMPARISON_COMPLETED = "comparison_completed"
    PREFERENCE_QUESTION_ANSWERED = "preference_question_answered"
    SUGGESTION_SHOWN = "system_suggestion_shown"
    SUGGESTION_ACCEPTED = "system_suggestion_accepted"
    SUGGESTION_REJECTED = "system_suggestion_rejected"
    SHORTLIST_SIZE_CHANGED = "shortlist_size_changed"
    SHORTLIST_RETURNED = "shortlist_returned_to"
    FINAL_CHOICE_SELECTED = "final_choice_selected"
    FINAL_CHOICE_CHANGED = "final_choice_changed"
    DECISION_REOPENED = "decision_reopened"


class DecisionAnalyticsClientEventType(StrEnum):
    """Events that an HTTP client may report directly.

    Mutation facts are server-authoritative and therefore intentionally absent
    from this enum.  The subset still covers view and interaction checkpoints.
    """

    SESSION_STARTED = DecisionAnalyticsEventType.SESSION_STARTED.value
    ADMISSION_FIT_VIEWED = DecisionAnalyticsEventType.ADMISSION_FIT_VIEWED.value
    COMPARISON_STARTED = DecisionAnalyticsEventType.COMPARISON_STARTED.value
    COMPARISON_COMPLETED = DecisionAnalyticsEventType.COMPARISON_COMPLETED.value
    PREFERENCE_QUESTION_ANSWERED = DecisionAnalyticsEventType.PREFERENCE_QUESTION_ANSWERED.value
    SUGGESTION_SHOWN = DecisionAnalyticsEventType.SUGGESTION_SHOWN.value
    SHORTLIST_RETURNED = DecisionAnalyticsEventType.SHORTLIST_RETURNED.value


class DecisionAnalyticsSource(StrEnum):
    CATALOG = "catalog"
    PROGRAM = "program"
    ADMISSION = "admission"
    COMPARE = "compare"
    DECISION = "decision"
    SUGGESTION = "suggestion"
    PROFTEST = "proftest"
    SYSTEM = "system"


class DecisionAnalyticsAction(StrEnum):
    VIEW = "view"
    START = "start"
    COMPLETE = "complete"
    CONSIDER = "consider"
    ADD = "add"
    REMOVE = "remove"
    RESTORE = "restore"
    MARK_PRIMARY = "mark_primary"
    MARK_ALTERNATIVE = "mark_alternative"
    SET_CONSTRAINTS = "set_constraints"
    ANSWER = "answer"
    SHOW = "show"
    ACCEPT = "accept"
    REJECT = "reject"
    RETURN = "return"


class DecisionAnalyticsStatus(StrEnum):
    REALISTIC = "realistic"
    BORDERLINE = "borderline"
    UNLIKELY = "unlikely"
    INSUFFICIENT_DATA = "insufficient_data"
    AVAILABLE = "available"
    PROVIDED = "provided"
    CLEARED = "cleared"
    STARTED = "started"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class DecisionAnalyticsPayload(ContractModel):
    """Small allow-listed payload shared by client and server events."""

    source: DecisionAnalyticsSource | None = None
    action: DecisionAnalyticsAction | None = None
    status: DecisionAnalyticsStatus | None = None
    program_id: ProgramId | None = None
    program_ids: tuple[ProgramId, ...] = Field(default=(), max_length=3)
    role: ShortlistRole | None = None
    count: int | None = Field(default=None, strict=True, ge=0, le=50)
    shortlist_size_before: int | None = Field(default=None, strict=True, ge=0, le=20)
    shortlist_size_after: int | None = Field(default=None, strict=True, ge=0, le=20)
    question_id: AnalyticsToken | None = None
    option_id: AnalyticsToken | None = None

    @model_validator(mode="after")
    def validate_bounded_values(self) -> Self:
        if len(self.program_ids) != len(set(self.program_ids)):
            raise ValueError("analytics program_ids must be unique")
        if self.shortlist_size_before is not None and self.shortlist_size_after is not None and self.shortlist_size_before == self.shortlist_size_after:
            raise ValueError("shortlist_size_changed must contain different sizes")
        return self


class DecisionAnalyticsClientEvent(ContractModel):
    """A client-submitted event before server timestamps and owner binding."""

    event_id: DecisionAnalyticsEventId
    event_type: DecisionAnalyticsEventType
    payload: DecisionAnalyticsPayload = Field(default_factory=DecisionAnalyticsPayload)

    @model_validator(mode="after")
    def validate_event_shape(self) -> Self:
        _validate_event_shape(self.event_type, self.payload)
        return self


class DecisionAnalyticsEvent(DecisionAnalyticsClientEvent):
    """Persisted event envelope with server-controlled retention timestamps."""

    occurred_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("analytics occurred_at must be timezone-aware")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("analytics expires_at must be timezone-aware")
        if self.expires_at <= self.occurred_at:
            raise ValueError("analytics expires_at must be after occurred_at")
        return self


class DecisionAnalyticsFunnel(ContractModel):
    """Privacy-safe aggregate for the Ops funnel.

    It contains only distinct owner counts and bounded shortlist-size facts;
    raw payloads, admission scores and profile answers never cross this read
    boundary.
    """

    decision_sessions: int = Field(strict=True, ge=0)
    shortlist_started: int = Field(strict=True, ge=0)
    comparison_started: int = Field(strict=True, ge=0)
    comparison_completed: int = Field(strict=True, ge=0)
    suggestion_shown: int = Field(strict=True, ge=0)
    suggestion_accepted: int = Field(strict=True, ge=0)
    final_choice_selected: int = Field(strict=True, ge=0)
    average_shortlist_size: float | None = Field(default=None, strict=True, ge=0, le=20)
    shortlist_conversion_percent: float | None = Field(default=None, strict=True, ge=0, le=100)
    comparison_conversion_percent: float | None = Field(default=None, strict=True, ge=0, le=100)
    final_choice_conversion_percent: float | None = Field(default=None, strict=True, ge=0, le=100)


def _validate_event_shape(event_type: DecisionAnalyticsEventType, payload: DecisionAnalyticsPayload) -> None:
    required_program = {
        DecisionAnalyticsEventType.PROGRAM_CONSIDERED,
        DecisionAnalyticsEventType.PROGRAM_ADDED,
        DecisionAnalyticsEventType.PROGRAM_REMOVED,
        DecisionAnalyticsEventType.PROGRAM_RESTORED,
        DecisionAnalyticsEventType.PROGRAM_MARKED_PRIMARY,
        DecisionAnalyticsEventType.PROGRAM_MARKED_ALTERNATIVE,
        DecisionAnalyticsEventType.SUGGESTION_SHOWN,
        DecisionAnalyticsEventType.SUGGESTION_ACCEPTED,
        DecisionAnalyticsEventType.SUGGESTION_REJECTED,
        DecisionAnalyticsEventType.FINAL_CHOICE_SELECTED,
        DecisionAnalyticsEventType.FINAL_CHOICE_CHANGED,
    }
    if event_type in required_program and payload.program_id is None:
        raise ValueError(f"{event_type.value} requires program_id")
    if event_type in {DecisionAnalyticsEventType.COMPARISON_STARTED, DecisionAnalyticsEventType.COMPARISON_COMPLETED}:
        if not 2 <= len(payload.program_ids) <= 3:
            raise ValueError(f"{event_type.value} requires two or three program_ids")
    if event_type is DecisionAnalyticsEventType.PREFERENCE_QUESTION_ANSWERED:
        if payload.question_id is None or payload.option_id is None:
            raise ValueError("preference_question_answered requires question_id and option_id")
    if event_type is DecisionAnalyticsEventType.SHORTLIST_SIZE_CHANGED:
        if payload.shortlist_size_before is None or payload.shortlist_size_after is None:
            raise ValueError("shortlist_size_changed requires before and after sizes")


__all__ = [
    "AnalyticsToken",
    "DecisionAnalyticsAction",
    "DecisionAnalyticsClientEvent",
    "DecisionAnalyticsClientEventType",
    "DecisionAnalyticsEvent",
    "DecisionAnalyticsEventId",
    "DecisionAnalyticsEventType",
    "DecisionAnalyticsFunnel",
    "DecisionAnalyticsPayload",
    "DecisionAnalyticsSource",
    "DecisionAnalyticsStatus",
]
