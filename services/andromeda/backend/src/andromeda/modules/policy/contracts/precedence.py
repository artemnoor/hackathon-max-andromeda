"""Structured, source-linked decisions made by the effective policy resolver."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.shared.contracts.base import ContractModel

from .applicability import PolicySelection
from .rule import PolicyRuleRelationKind


class PolicyPrecedenceOutcome(StrEnum):
    LEFT_PREVAILS = "left_prevails"
    RIGHT_PREVAILS = "right_prevails"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


class PolicyPrecedenceReason(StrEnum):
    EXACT_RELATION = "exact_relation"
    AUTHORIZED_EXCEPTION = "authorized_exception"
    AUTHORITY = "authority"
    SPECIFICITY = "specificity"
    EQUAL_PRECEDENCE = "equal_precedence"
    INCOMPARABLE_SCOPE = "incomparable_scope"
    CROSSING_AUTHORITY_AND_SCOPE = "crossing_authority_and_scope"
    UNRESOLVED_AUTHORITY = "unresolved_authority"
    AMBIGUOUS_RELATION_SET = "ambiguous_relation_set"
    PRECEDENCE_CYCLE = "precedence_cycle"


class PolicyPrecedenceDecision(ContractModel):
    left: PolicySelection
    right: PolicySelection
    outcome: PolicyPrecedenceOutcome
    reason: PolicyPrecedenceReason
    winner: PolicySelection | None = None
    relation_kind: PolicyRuleRelationKind | None = None
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def winner_matches_outcome(self) -> PolicyPrecedenceDecision:
        if self.outcome is PolicyPrecedenceOutcome.LEFT_PREVAILS:
            if self.winner != self.left:
                raise ValueError("left-precedence decision must identify the left rule as winner")
        elif self.outcome is PolicyPrecedenceOutcome.RIGHT_PREVAILS:
            if self.winner != self.right:
                raise ValueError("right-precedence decision must identify the right rule as winner")
        elif self.winner is not None:
            raise ValueError("conflict or indeterminate decisions cannot choose a winner")
        if (
            self.reason is PolicyPrecedenceReason.AUTHORIZED_EXCEPTION
            and self.relation_kind is not PolicyRuleRelationKind.AUTHORIZED_EXCEPTION_TO
        ):
            raise ValueError("authorized exception decisions must retain their exact relation kind")
        return self


class PolicyPrecedenceResult(ContractModel):
    effective_rules: tuple[PolicySelection, ...] = Field(default=(), max_length=500)
    conflicting_rules: tuple[PolicySelection, ...] = Field(default=(), max_length=500)
    decisions: tuple[PolicyPrecedenceDecision, ...] = Field(default=(), max_length=5000)
    status: Literal["resolved", "conflict", "indeterminate"]
    truncated: bool = False

    @model_validator(mode="after")
    def selected_and_conflicting_are_disjoint(self) -> PolicyPrecedenceResult:
        selected = {_selection_key(item) for item in self.effective_rules}
        conflicts = {_selection_key(item) for item in self.conflicting_rules}
        if len(selected) != len(self.effective_rules) or len(conflicts) != len(self.conflicting_rules):
            raise ValueError("precedence output selections must be unique")
        if selected & conflicts:
            raise ValueError("a rule cannot be both effective and in an unresolved conflict")
        if self.status == "resolved" and (self.conflicting_rules or not self.effective_rules):
            raise ValueError("resolved precedence requires effective rules and no conflicts")
        if self.status == "conflict" and not self.conflicting_rules:
            raise ValueError("conflict status requires exact conflicting rules")
        if self.status == "indeterminate" and self.effective_rules:
            raise ValueError("indeterminate precedence cannot expose effective rules")
        if self.truncated and self.status != "indeterminate":
            raise ValueError("truncated precedence must fail closed as indeterminate")
        return self


def _selection_key(selection: PolicySelection) -> tuple[str, int, str]:
    return selection.rule_id, selection.revision, selection.revision_hash


__all__ = [
    "PolicyPrecedenceDecision",
    "PolicyPrecedenceOutcome",
    "PolicyPrecedenceReason",
    "PolicyPrecedenceResult",
]
