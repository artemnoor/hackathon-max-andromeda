"""Typed inputs and explanations for deterministic policy applicability selection."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .rule import DomainRuleRef, PolicyRuleId, PolicyScope
from .rule_ast import PolicyContextField, PolicySelectorScalar


class PolicyContextAvailability(StrEnum):
    PRESENT = "present"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class PolicyContextOrigin(StrEnum):
    USER_PROVIDED = "user_provided"
    SOURCE_BACKED_CYCLE = "source_backed_cycle"
    DERIVED_FROM_EXPLICIT_INPUT = "derived_from_explicit_input"


class PolicyContextValue(ContractModel):
    field: PolicyContextField
    availability: PolicyContextAvailability
    origin: PolicyContextOrigin = PolicyContextOrigin.USER_PROVIDED
    value: PolicySelectorScalar | None = None

    @model_validator(mode="after")
    def value_matches_availability(self) -> PolicyContextValue:
        if (self.availability is PolicyContextAvailability.PRESENT) != (self.value is not None):
            raise ValueError("present context values require one scalar; unknown values require none")
        if self.value is not None:
            if self.field is PolicyContextField.ADMISSION_YEAR:
                if type(self.value) is not int:
                    raise ValueError("admission_year context must be an integer")
            elif type(self.value) is not str:
                raise ValueError(f"{self.field.value} context must be text")
        return self


class PolicyApplicabilityContext(ContractModel):
    values: tuple[PolicyContextValue, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def context_fields_are_unique(self) -> PolicyApplicabilityContext:
        fields = tuple(item.field for item in self.values)
        if len(fields) != len(set(fields)):
            raise ValueError("policy context fields must be unique")
        return self

    def value_for(self, field: PolicyContextField) -> PolicyContextValue:
        return next(
            (item for item in self.values if item.field is field),
            PolicyContextValue(field=field, availability=PolicyContextAvailability.UNKNOWN),
        )


class SelectorNodeState(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    INDETERMINATE = "indeterminate"


class SelectorNodeReason(StrEnum):
    VALUE_MATCHED = "value_matched"
    VALUE_DID_NOT_MATCH = "value_did_not_match"
    VALUE_PRESENT = "value_present"
    FIELD_UNKNOWN = "field_unknown"
    FIELD_UNAVAILABLE = "field_unavailable"
    ALL_CHILDREN_MATCHED = "all_children_matched"
    ANY_CHILD_MATCHED = "any_child_matched"
    CHILD_DID_NOT_MATCH = "child_did_not_match"
    CHILD_RESULT_UNKNOWN = "child_result_unknown"


class PolicyApplicabilityStatus(StrEnum):
    SELECTOR_MATCHED = "selector_matched"
    SELECTOR_NOT_MATCHED = "selector_not_matched"
    INDETERMINATE = "indeterminate"
    UNAPPROVED = "unapproved"
    UNSUPPORTED = "unsupported"


class PolicyDomainLookupStatus(StrEnum):
    AVAILABLE = "available"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class PolicyApplicabilityReason(StrEnum):
    SELECTOR_MATCHED = "selector_matched"
    SELECTOR_NOT_MATCHED = "selector_not_matched"
    REQUIRED_CONTEXT_UNKNOWN = "required_context_unknown"
    REVISION_NOT_APPROVED = "revision_not_approved"
    REVISION_HASH_MISMATCH = "revision_hash_mismatch"
    OWNER_PORT_NOT_REGISTERED = "owner_port_not_registered"
    OWNER_RULE_NOT_FOUND = "owner_rule_not_found"
    OWNER_LOOKUP_UNAVAILABLE = "owner_lookup_unavailable"


class PolicyScopeMatchState(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    INDETERMINATE = "indeterminate"


class PolicyScopeMatchReason(StrEnum):
    FEDERAL_SCOPE = "federal_scope"
    CONTEXT_MATCHED = "context_matched"
    CONTEXT_UNKNOWN = "context_unknown"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    CONTEXT_MISMATCHED = "context_mismatched"


class PolicyScopeAssessment(ContractModel):
    scope: PolicyScope
    state: PolicyScopeMatchState
    reason: PolicyScopeMatchReason


class PolicyDomainRuleLookup(ContractModel):
    requested_reference: DomainRuleRef
    status: PolicyDomainLookupStatus
    resolved_reference: DomainRuleRef | None = None

    @model_validator(mode="after")
    def only_available_lookup_returns_exact_reference(self) -> PolicyDomainRuleLookup:
        if (self.status is PolicyDomainLookupStatus.AVAILABLE) != (
            self.resolved_reference == self.requested_reference
        ):
            raise ValueError("available owner lookup must return the exact requested revision")
        if self.status is not PolicyDomainLookupStatus.AVAILABLE and self.resolved_reference is not None:
            raise ValueError("unavailable owner lookup cannot return a resolved rule reference")
        return self


class SelectorNodeTrace(ContractModel):
    node_id: Annotated[str, Field(min_length=1, max_length=32)]
    state: SelectorNodeState
    reason: SelectorNodeReason


class PolicySelection(ContractModel):
    """An exact owner-managed rule reference; this contract contains no domain result."""

    rule_id: PolicyRuleId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    revision_hash: SourceHash
    domain_rule: DomainRuleRef


class PolicyApplicabilityAssessment(ContractModel):
    rule_id: PolicyRuleId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    revision_hash: SourceHash
    status: PolicyApplicabilityStatus
    reason: PolicyApplicabilityReason
    node_trace: tuple[SelectorNodeTrace, ...] = Field(max_length=64)
    selection: PolicySelection | None = None
    domain_lookup: PolicyDomainLookupStatus | None = None

    @model_validator(mode="after")
    def selection_only_when_owner_reference_is_available(self) -> PolicyApplicabilityAssessment:
        has_selection = self.selection is not None
        if has_selection != (self.status is PolicyApplicabilityStatus.SELECTOR_MATCHED):
            raise ValueError("only a matched selector may expose an owner rule selection")
        if has_selection != (self.domain_lookup is PolicyDomainLookupStatus.AVAILABLE):
            raise ValueError("policy selection requires an available exact owner revision")
        return self


__all__ = [
    "PolicyApplicabilityAssessment",
    "PolicyApplicabilityContext",
    "PolicyApplicabilityReason",
    "PolicyApplicabilityStatus",
    "PolicyContextAvailability",
    "PolicyContextOrigin",
    "PolicyContextValue",
    "PolicyDomainLookupStatus",
    "PolicyDomainRuleLookup",
    "PolicyScopeAssessment",
    "PolicyScopeMatchReason",
    "PolicyScopeMatchState",
    "PolicySelection",
    "SelectorNodeReason",
    "SelectorNodeState",
    "SelectorNodeTrace",
]
