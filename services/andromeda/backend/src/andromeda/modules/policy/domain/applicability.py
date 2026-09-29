"""Pure, fail-closed evaluation of a bounded selector AST against typed context."""

from __future__ import annotations

from andromeda.modules.policy.contracts.applicability import (
    PolicyApplicabilityContext,
    PolicyContextAvailability,
    PolicyScopeAssessment,
    PolicyScopeMatchReason,
    PolicyScopeMatchState,
    SelectorNodeReason,
    SelectorNodeState,
    SelectorNodeTrace,
)
from andromeda.modules.policy.contracts.rule import PolicyScope, PolicyScopeLevel
from andromeda.modules.policy.contracts.rule_ast import (
    PolicyContextField,
    PolicySelectorAst,
    PolicySelectorNode,
    PolicySelectorNodeKind,
)
from andromeda.modules.policy.domain.field_registry import (
    validate_registered_context_value,
    validate_selector_ast,
)


def evaluate_policy_selector(
    selector: PolicySelectorAst,
    context: PolicyApplicabilityContext,
) -> tuple[SelectorNodeTrace, ...]:
    """Return stable per-node states; unknown context is never treated as false."""
    validate_selector_ast(selector)
    for item in context.values:
        if item.availability is PolicyContextAvailability.PRESENT:
            validate_registered_context_value(item.field, item.value)

    children: dict[str, list[PolicySelectorNode]] = {
        node.node_id: [] for node in selector.nodes
    }
    root = next(node for node in selector.nodes if node.parent_id is None)
    for node in selector.nodes:
        if node.parent_id is not None:
            children[node.parent_id].append(node)

    postorder: list[PolicySelectorNode] = []
    stack: list[tuple[PolicySelectorNode, bool]] = [(root, False)]
    while stack:
        node, visited = stack.pop()
        if visited:
            postorder.append(node)
            continue
        stack.append((node, True))
        stack.extend((child, False) for child in reversed(children[node.node_id]))

    outcomes: dict[str, tuple[SelectorNodeState, SelectorNodeReason]] = {}
    for node in postorder:
        if node.kind in {PolicySelectorNodeKind.ALL, PolicySelectorNodeKind.ANY}:
            child_states = tuple(outcomes[child.node_id][0] for child in children[node.node_id])
            outcomes[node.node_id] = _combine(node.kind, child_states)
        else:
            outcomes[node.node_id] = _evaluate_leaf(node, context)

    return tuple(
        SelectorNodeTrace(
            node_id=node.node_id,
            state=outcomes[node.node_id][0],
            reason=outcomes[node.node_id][1],
        )
        for node in selector.nodes
    )


_SCOPE_CONTEXT_FIELDS: dict[PolicyScopeLevel, PolicyContextField] = {
    PolicyScopeLevel.MINISTRY: PolicyContextField.REGULATOR_ID,
    PolicyScopeLevel.UNIVERSITY: PolicyContextField.UNIVERSITY_ID,
    PolicyScopeLevel.CAMPUS: PolicyContextField.CAMPUS_ID,
    PolicyScopeLevel.FACULTY: PolicyContextField.FACULTY_ID,
    PolicyScopeLevel.DEPARTMENT: PolicyContextField.DEPARTMENT_ID,
    PolicyScopeLevel.EDUCATION_LEVEL: PolicyContextField.EDUCATION_LEVEL,
    PolicyScopeLevel.DIRECTION: PolicyContextField.DIRECTION_ID,
    PolicyScopeLevel.PROGRAM: PolicyContextField.PROGRAM_ID,
    PolicyScopeLevel.ADMISSION_ROUTE: PolicyContextField.ADMISSION_ROUTE,
    PolicyScopeLevel.COMPETITION_TYPE: PolicyContextField.COMPETITION_TYPE,
    PolicyScopeLevel.APPLICANT_CATEGORY: PolicyContextField.APPLICANT_CATEGORY,
    PolicyScopeLevel.OLYMPIAD: PolicyContextField.OLYMPIAD_ID,
    PolicyScopeLevel.OLYMPIAD_PROFILE: PolicyContextField.OLYMPIAD_PROFILE_ID,
    PolicyScopeLevel.SUBJECT: PolicyContextField.SUBJECT_ID,
}


def assess_policy_scope(
    scope: PolicyScope,
    context: PolicyApplicabilityContext,
) -> PolicyScopeAssessment:
    """Match an explicit scope against one typed context dimension."""
    if scope.level is PolicyScopeLevel.FEDERAL:
        return PolicyScopeAssessment(
            scope=scope,
            state=PolicyScopeMatchState.MATCH,
            reason=PolicyScopeMatchReason.FEDERAL_SCOPE,
        )
    value = context.value_for(_SCOPE_CONTEXT_FIELDS[scope.level])
    if value.availability is PolicyContextAvailability.UNKNOWN:
        return PolicyScopeAssessment(
            scope=scope,
            state=PolicyScopeMatchState.INDETERMINATE,
            reason=PolicyScopeMatchReason.CONTEXT_UNKNOWN,
        )
    if value.availability is PolicyContextAvailability.UNAVAILABLE:
        return PolicyScopeAssessment(
            scope=scope,
            state=PolicyScopeMatchState.INDETERMINATE,
            reason=PolicyScopeMatchReason.CONTEXT_UNAVAILABLE,
        )
    if value.value != scope.scope_id:
        return PolicyScopeAssessment(
            scope=scope,
            state=PolicyScopeMatchState.NO_MATCH,
            reason=PolicyScopeMatchReason.CONTEXT_MISMATCHED,
        )
    return PolicyScopeAssessment(
        scope=scope,
        state=PolicyScopeMatchState.MATCH,
        reason=PolicyScopeMatchReason.CONTEXT_MATCHED,
    )


def _evaluate_leaf(
    node: PolicySelectorNode,
    context: PolicyApplicabilityContext,
) -> tuple[SelectorNodeState, SelectorNodeReason]:
    assert node.field is not None
    value = context.value_for(node.field)
    if value.availability is PolicyContextAvailability.UNKNOWN:
        return SelectorNodeState.INDETERMINATE, SelectorNodeReason.FIELD_UNKNOWN
    if value.availability is PolicyContextAvailability.UNAVAILABLE:
        return SelectorNodeState.INDETERMINATE, SelectorNodeReason.FIELD_UNAVAILABLE

    if node.kind is PolicySelectorNodeKind.EXISTS:
        return SelectorNodeState.MATCH, SelectorNodeReason.VALUE_PRESENT
    if node.kind is PolicySelectorNodeKind.EQUALS:
        matches = type(value.value) is type(node.value) and value.value == node.value
    else:
        matches = any(
            type(value.value) is type(candidate) and value.value == candidate
            for candidate in node.values
        )
    return (
        (SelectorNodeState.MATCH, SelectorNodeReason.VALUE_MATCHED)
        if matches
        else (SelectorNodeState.NO_MATCH, SelectorNodeReason.VALUE_DID_NOT_MATCH)
    )


def _combine(
    kind: PolicySelectorNodeKind,
    states: tuple[SelectorNodeState, ...],
) -> tuple[SelectorNodeState, SelectorNodeReason]:
    if kind is PolicySelectorNodeKind.ALL:
        if SelectorNodeState.NO_MATCH in states:
            return SelectorNodeState.NO_MATCH, SelectorNodeReason.CHILD_DID_NOT_MATCH
        if SelectorNodeState.INDETERMINATE in states:
            return SelectorNodeState.INDETERMINATE, SelectorNodeReason.CHILD_RESULT_UNKNOWN
        return SelectorNodeState.MATCH, SelectorNodeReason.ALL_CHILDREN_MATCHED
    if SelectorNodeState.MATCH in states:
        return SelectorNodeState.MATCH, SelectorNodeReason.ANY_CHILD_MATCHED
    if SelectorNodeState.INDETERMINATE in states:
        return SelectorNodeState.INDETERMINATE, SelectorNodeReason.CHILD_RESULT_UNKNOWN
    return SelectorNodeState.NO_MATCH, SelectorNodeReason.CHILD_DID_NOT_MATCH


__all__ = ["assess_policy_scope", "evaluate_policy_selector"]
