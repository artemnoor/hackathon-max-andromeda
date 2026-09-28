"""Domain-facing aliases for source-backed change event candidates."""

from ..contracts.public import (
    ChangeEvent,
    ChangeEventKind,
    ChangeEventReviewState,
    ClaimRevisionRef,
)

CHANGE_EVENT_REVIEW_TRANSITIONS: dict[
    ChangeEventReviewState, frozenset[ChangeEventReviewState]
] = {
    ChangeEventReviewState.NEEDS_REVIEW: frozenset(
        {
            ChangeEventReviewState.ACCEPTED_AS_SOURCE_EVENT,
            ChangeEventReviewState.REJECTED,
            ChangeEventReviewState.UNRESOLVED,
            ChangeEventReviewState.DUPLICATE,
        }
    ),
    ChangeEventReviewState.ACCEPTED_AS_SOURCE_EVENT: frozenset(
        {
            ChangeEventReviewState.NEEDS_REVIEW,
            ChangeEventReviewState.UNRESOLVED,
            ChangeEventReviewState.DUPLICATE,
        }
    ),
    ChangeEventReviewState.REJECTED: frozenset(),
    ChangeEventReviewState.UNRESOLVED: frozenset(
        {
            ChangeEventReviewState.NEEDS_REVIEW,
            ChangeEventReviewState.REJECTED,
            ChangeEventReviewState.DUPLICATE,
        }
    ),
    ChangeEventReviewState.DUPLICATE: frozenset(),
}


def transition_change_event_review(
    current: ChangeEventReviewState, target: ChangeEventReviewState
) -> ChangeEventReviewState:
    if target not in CHANGE_EVENT_REVIEW_TRANSITIONS[current]:
        raise ValueError(
            f"unsupported change-event review transition: {current.value} -> {target.value}"
        )
    return target


__all__ = [
    "CHANGE_EVENT_REVIEW_TRANSITIONS",
    "ChangeEvent",
    "ChangeEventKind",
    "ChangeEventReviewState",
    "ClaimRevisionRef",
    "transition_change_event_review",
]
