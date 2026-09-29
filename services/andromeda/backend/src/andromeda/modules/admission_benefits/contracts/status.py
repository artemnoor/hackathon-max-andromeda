from __future__ import annotations

from enum import StrEnum

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SemanticVersion


class RuleDataStatus(StrEnum):
    """Lifecycle state of a source-backed legal rule."""

    ACTIVE = "active"
    STALE = "stale"
    REVIEW_REQUIRED = "review_required"
    CONFLICT = "conflict"
    UNRESOLVED = "unresolved"


class ApplicabilityStatus(StrEnum):
    """Result of evaluating a rule against the data available to a caller."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_DATA = "insufficient_data"
    REVIEW_REQUIRED = "review_required"


class TargetResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


_ALLOWED_STATUS_TRANSITIONS: dict[RuleDataStatus, frozenset[RuleDataStatus]] = {
    RuleDataStatus.ACTIVE: frozenset(
        {RuleDataStatus.ACTIVE, RuleDataStatus.STALE, RuleDataStatus.REVIEW_REQUIRED, RuleDataStatus.CONFLICT}
    ),
    RuleDataStatus.STALE: frozenset(
        {RuleDataStatus.STALE, RuleDataStatus.ACTIVE, RuleDataStatus.REVIEW_REQUIRED, RuleDataStatus.CONFLICT}
    ),
    RuleDataStatus.REVIEW_REQUIRED: frozenset(
        {RuleDataStatus.REVIEW_REQUIRED, RuleDataStatus.ACTIVE, RuleDataStatus.STALE, RuleDataStatus.CONFLICT}
    ),
    RuleDataStatus.CONFLICT: frozenset(
        {RuleDataStatus.CONFLICT, RuleDataStatus.REVIEW_REQUIRED, RuleDataStatus.ACTIVE}
    ),
    RuleDataStatus.UNRESOLVED: frozenset(
        {RuleDataStatus.UNRESOLVED, RuleDataStatus.REVIEW_REQUIRED, RuleDataStatus.ACTIVE}
    ),
}


def can_transition_status(current: RuleDataStatus, target: RuleDataStatus) -> bool:
    """Return whether a refresh may move a rule between lifecycle states."""

    return target in _ALLOWED_STATUS_TRANSITIONS[current]


class BenefitPolicyVersion(ContractModel):
    """Reproducibility identifiers for benefit contracts and parser policy."""

    schema_version: SemanticVersion
    parser_version: SemanticVersion
    policy_version: SemanticVersion


__all__ = [
    "ApplicabilityStatus",
    "BenefitPolicyVersion",
    "RuleDataStatus",
    "TargetResolutionStatus",
    "can_transition_status",
]
