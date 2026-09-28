"""Domain-facing source assertion types and review transition table."""

from ..contracts.public import (
    Claim,
    ClaimedPolicyStage,
    ClaimProposition,
    ClaimReviewState,
)

CLAIM_REVIEW_TRANSITIONS: dict[ClaimReviewState, frozenset[ClaimReviewState]] = {
    ClaimReviewState.UNREVIEWED: frozenset(
        {ClaimReviewState.NEEDS_REVIEW, ClaimReviewState.UNRESOLVED}
    ),
    ClaimReviewState.NEEDS_REVIEW: frozenset(
        {
            ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION,
            ClaimReviewState.REJECTED,
            ClaimReviewState.UNRESOLVED,
            ClaimReviewState.DUPLICATE,
        }
    ),
    ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION: frozenset(
        {
            ClaimReviewState.NEEDS_REVIEW,
            ClaimReviewState.UNRESOLVED,
            ClaimReviewState.DUPLICATE,
        }
    ),
    ClaimReviewState.UNRESOLVED: frozenset(
        {ClaimReviewState.NEEDS_REVIEW, ClaimReviewState.REJECTED, ClaimReviewState.DUPLICATE}
    ),
    ClaimReviewState.REJECTED: frozenset(),
    ClaimReviewState.DUPLICATE: frozenset(),
}


def transition_claim_review(
    current: ClaimReviewState, target: ClaimReviewState
) -> ClaimReviewState:
    if target not in CLAIM_REVIEW_TRANSITIONS[current]:
        raise ValueError(f"unsupported claim review transition: {current.value} -> {target.value}")
    return target


__all__ = [
    "CLAIM_REVIEW_TRANSITIONS",
    "Claim",
    "ClaimProposition",
    "ClaimReviewState",
    "ClaimedPolicyStage",
    "transition_claim_review",
]
