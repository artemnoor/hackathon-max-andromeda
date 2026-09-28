"""Decision analytics facade with no influence on decision state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.shared.contracts.errors import ValidationError

from ..contracts.public import (
    DecisionAnalyticsAction,
    DecisionAnalyticsClientEvent,
    DecisionAnalyticsEvent,
    DecisionAnalyticsEventType,
    DecisionAnalyticsPayload,
    DecisionAnalyticsSource,
    DecisionAnalyticsStatus,
    DecisionAnalyticsWriter,
    ShortlistRole,
)
from ..domain.entities import DecisionState
from ..domain.values import ShortlistEntryState


logger = logging.getLogger("andromeda.modules.decision.analytics")

DEFAULT_ANALYTICS_TTL_SECONDS = 180 * 24 * 60 * 60
CLIENT_EVENT_TYPES = frozenset(
    {
        DecisionAnalyticsEventType.SESSION_STARTED,
        DecisionAnalyticsEventType.ADMISSION_FIT_VIEWED,
        DecisionAnalyticsEventType.COMPARISON_STARTED,
        DecisionAnalyticsEventType.COMPARISON_COMPLETED,
        DecisionAnalyticsEventType.PREFERENCE_QUESTION_ANSWERED,
        DecisionAnalyticsEventType.SUGGESTION_SHOWN,
        DecisionAnalyticsEventType.SHORTLIST_RETURNED,
    }
)


class DecisionAnalyticsService:
    """Serialize bounded analytics and isolate storage failures.

    The decision service calls ``record_mutation`` only after its repository
    commits.  This facade never reads analytics back and never raises storage
    exceptions to the user-facing mutation path.
    """

    def __init__(
        self,
        writer: DecisionAnalyticsWriter,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = DEFAULT_ANALYTICS_TTL_SECONDS,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self._writer = writer
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._ttl_seconds = ttl_seconds

    def record_client_event(self, scope: ProfileScope, event: DecisionAnalyticsClientEvent) -> int:
        """Accept only the non-authoritative client event subset."""

        if event.event_type not in CLIENT_EVENT_TYPES:
            raise ValidationError("This decision analytics event must be emitted by the server")
        if event.payload.shortlist_size_before is not None or event.payload.shortlist_size_after is not None:
            raise ValidationError("Shortlist sizes are server-authoritative")
        now = self._now()
        persisted = DecisionAnalyticsEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            payload=event.payload,
            occurred_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
        )
        return self._append_safe(scope, (persisted,))

    def record_mutation(
        self,
        scope: ProfileScope,
        *,
        operation: str,
        program_id: str | None,
        before: DecisionState,
        after: DecisionState,
    ) -> int:
        """Record facts from one committed, explicit state transition."""

        events = self._events_for_mutation(operation, program_id=program_id, before=before, after=after)
        return self._append_safe(scope, events)

    def _events_for_mutation(
        self,
        operation: str,
        *,
        program_id: str | None,
        before: DecisionState,
        after: DecisionState,
    ) -> tuple[DecisionAnalyticsEvent, ...]:
        now = self._now()
        generated: list[DecisionAnalyticsEvent] = []

        def add(
            event_type: DecisionAnalyticsEventType,
            *,
            source: DecisionAnalyticsSource = DecisionAnalyticsSource.DECISION,
            action: DecisionAnalyticsAction | None = None,
            status: DecisionAnalyticsStatus | None = None,
            role: ShortlistRole | None = None,
        ) -> None:
            payload = DecisionAnalyticsPayload(
                source=source,
                action=action,
                status=status,
                program_id=program_id,
                role=role,
            )
            generated.append(self._event(event_type, payload, now))

        if operation == "mark_considered":
            add(DecisionAnalyticsEventType.PROGRAM_CONSIDERED, action=DecisionAnalyticsAction.CONSIDER)
        elif operation == "add_shortlist":
            role = _active_role(after, program_id)
            add(DecisionAnalyticsEventType.PROGRAM_ADDED, action=DecisionAnalyticsAction.ADD, role=role)
        elif operation == "remove_shortlist":
            add(DecisionAnalyticsEventType.PROGRAM_REMOVED, action=DecisionAnalyticsAction.REMOVE)
        elif operation == "restore_shortlist":
            role = _active_role(after, program_id)
            add(DecisionAnalyticsEventType.PROGRAM_RESTORED, action=DecisionAnalyticsAction.RESTORE, role=role)
        elif operation == "set_shortlist_role":
            role = _active_role(after, program_id)
            if role is not None:
                add(
                    DecisionAnalyticsEventType.PROGRAM_MARKED_PRIMARY
                    if role is ShortlistRole.PRIMARY
                    else DecisionAnalyticsEventType.PROGRAM_MARKED_ALTERNATIVE,
                    action=DecisionAnalyticsAction.MARK_PRIMARY
                    if role is ShortlistRole.PRIMARY
                    else DecisionAnalyticsAction.MARK_ALTERNATIVE,
                    role=role,
                )
        elif operation == "update_constraints":
            add(
                DecisionAnalyticsEventType.ADMISSION_CONSTRAINTS_ADDED,
                action=DecisionAnalyticsAction.SET_CONSTRAINTS,
                status=DecisionAnalyticsStatus.PROVIDED
                if after.admission_constraints is not None
                else DecisionAnalyticsStatus.CLEARED,
            )
        elif operation == "accept_suggestion":
            role = _active_role(after, program_id)
            add(
                DecisionAnalyticsEventType.SUGGESTION_ACCEPTED,
                source=DecisionAnalyticsSource.SUGGESTION,
                action=DecisionAnalyticsAction.ACCEPT,
                role=role,
            )
            add(
                DecisionAnalyticsEventType.PROGRAM_ADDED,
                source=DecisionAnalyticsSource.SUGGESTION,
                action=DecisionAnalyticsAction.ADD,
                role=role,
            )
        elif operation == "reject_suggestion":
            add(
                DecisionAnalyticsEventType.SUGGESTION_REJECTED,
                source=DecisionAnalyticsSource.SUGGESTION,
                action=DecisionAnalyticsAction.REJECT,
            )
        elif operation == "select_final_choice":
            add(
                DecisionAnalyticsEventType.FINAL_CHOICE_CHANGED
                if before.selected_program_id is not None
                else DecisionAnalyticsEventType.FINAL_CHOICE_SELECTED,
                action=DecisionAnalyticsAction.COMPLETE,
            )
        elif operation == "reopen_final_choice":
            add(DecisionAnalyticsEventType.DECISION_REOPENED, action=DecisionAnalyticsAction.RETURN)

        before_size = len(before.choice.active_shortlist)
        after_size = len(after.choice.active_shortlist)
        if before_size != after_size:
            generated.append(
                self._event(
                    DecisionAnalyticsEventType.SHORTLIST_SIZE_CHANGED,
                    DecisionAnalyticsPayload(
                        source=DecisionAnalyticsSource.DECISION,
                        action=DecisionAnalyticsAction.ADD
                        if after_size > before_size
                        else DecisionAnalyticsAction.REMOVE,
                        program_id=program_id,
                        shortlist_size_before=before_size,
                        shortlist_size_after=after_size,
                    ),
                    now,
                )
            )
        return tuple(generated)

    def _event(
        self,
        event_type: DecisionAnalyticsEventType,
        payload: DecisionAnalyticsPayload,
        occurred_at: datetime,
    ) -> DecisionAnalyticsEvent:
        return DecisionAnalyticsEvent(
            event_id=f"decision-event:{uuid4().hex}",
            event_type=event_type,
            payload=payload,
            occurred_at=occurred_at,
            expires_at=occurred_at + timedelta(seconds=self._ttl_seconds),
        )

    def _append_safe(self, scope: ProfileScope, events: tuple[DecisionAnalyticsEvent, ...]) -> int:
        if not events:
            return 0
        try:
            return self._writer.append(scope, events)
        except Exception as exc:  # telemetry must not alter a committed choice
            logger.warning(
                "decision_analytics_append_failed event_count=%d outcome=ignored error_type=%s",
                len(events),
                type(exc).__name__,
            )
            return 0

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("analytics clock must be timezone-aware")
        return now


def _active_role(state: DecisionState, program_id: str | None) -> ShortlistRole | None:
    if program_id is None:
        return None
    entry = next(
        (
            item
            for item in state.choice.shortlist_entries
            if item.program_id == program_id and item.state is ShortlistEntryState.ACTIVE
        ),
        None,
    )
    return entry.role if entry is not None else None


__all__ = ["CLIENT_EVENT_TYPES", "DEFAULT_ANALYTICS_TTL_SECONDS", "DecisionAnalyticsService"]
