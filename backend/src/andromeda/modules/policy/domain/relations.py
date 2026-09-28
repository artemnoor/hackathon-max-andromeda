"""Pure validation for typed policy-rule relations."""

from __future__ import annotations

from andromeda.modules.policy.contracts.rule import (
    PolicyAuthorityLevel,
    PolicyRuleRelationKind,
    PolicyRuleRevision,
)
from andromeda.modules.policy.domain.precedence import (
    ScopeSpecificity,
    scope_specificity,
)

_AUTHORITY_RANK: dict[PolicyAuthorityLevel, int] = {
    PolicyAuthorityLevel.FEDERAL_NORMATIVE: 3,
    PolicyAuthorityLevel.REGULATOR_NORMATIVE: 2,
    PolicyAuthorityLevel.UNIVERSITY_NORMATIVE: 1,
}
_MAX_REQUIREMENT_EDGES = 10_000
_MAX_REQUIREMENT_NODES = 1_000


def validate_policy_relations(
    revision: PolicyRuleRevision,
    *,
    approved_targets: tuple[PolicyRuleRevision, ...],
    approved_revisions: tuple[PolicyRuleRevision, ...],
) -> None:
    """Validate authority/scope semantics and requirement acyclicity.

    Repository adapters resolve exact target identities and approval at the
    revision's knowledge time. This function owns only domain interpretation.
    """
    if len(approved_targets) != len(revision.relations):
        raise ValueError("policy relation targets must match the submitted relation set")

    for relation, target_revision in zip(
        revision.relations, approved_targets, strict=True
    ):
        if (
            relation.target_rule_id,
            relation.target_revision,
            relation.target_hash,
        ) != (
            target_revision.rule_id,
            target_revision.revision,
            target_revision.content_hash,
        ):
            raise ValueError("policy relation target must be the exact approved revision")
        if (
            relation.kind is not PolicyRuleRelationKind.REQUIRES
            and target_revision.family_id != revision.family_id
        ):
            raise ValueError(
                "Policy precedence relations must stay within one rule family"
            )
        if relation.kind is PolicyRuleRelationKind.REQUIRES:
            continue
        if target_revision.authority is None or revision.authority is None:
            raise ValueError("Policy relations require classified legal authority")

        specificity = scope_specificity(revision.scope, target_revision.scope)
        if relation.kind is PolicyRuleRelationKind.AUTHORIZED_EXCEPTION_TO:
            if (
                revision.authority is PolicyAuthorityLevel.UNRESOLVED
                or target_revision.authority is PolicyAuthorityLevel.UNRESOLVED
                or specificity is not ScopeSpecificity.LEFT_NARROWER
            ):
                raise ValueError(
                    "Authorized policy exceptions require resolved authority and a strictly narrower scope"
                )
        elif relation.kind in {
            PolicyRuleRelationKind.OVERRIDES,
            PolicyRuleRelationKind.SUPERSEDES,
            PolicyRuleRelationKind.AMENDS,
        } and (
            revision.authority is PolicyAuthorityLevel.UNRESOLVED
            or target_revision.authority is PolicyAuthorityLevel.UNRESOLVED
            or _AUTHORITY_RANK[revision.authority]
            < _AUTHORITY_RANK[target_revision.authority]
            or specificity
            not in {ScopeSpecificity.EQUAL, ScopeSpecificity.LEFT_NARROWER}
        ):
            raise ValueError(
                "Policy overrides require sufficient authority and an equal or narrower scope"
            )

    requirement_edges: list[tuple[tuple[str, int], tuple[str, int]]] = []
    source = (revision.rule_id, revision.revision)
    for approved in approved_revisions:
        if (approved.rule_id, approved.revision) == source:
            continue
        for relation in approved.relations:
            if relation.kind is PolicyRuleRelationKind.REQUIRES:
                requirement_edges.append(
                    (
                        (approved.rule_id, approved.revision),
                        (relation.target_rule_id, relation.target_revision),
                    )
                )
    if len(requirement_edges) > _MAX_REQUIREMENT_EDGES:
        raise ValueError(
            "Policy requirement cycle check exceeds the 10000-edge limit"
        )

    adjacency: dict[tuple[str, int], set[tuple[str, int]]] = {}
    for edge_source, edge_target in requirement_edges:
        adjacency.setdefault(edge_source, set()).add(edge_target)
    new_targets = tuple(
        (target_revision.rule_id, target_revision.revision)
        for relation, target_revision in zip(
            revision.relations, approved_targets, strict=True
        )
        if relation.kind is PolicyRuleRelationKind.REQUIRES
    )
    adjacency.setdefault(source, set()).update(new_targets)

    for target_identity in new_targets:
        pending = [target_identity]
        visited: set[tuple[str, int]] = set()
        while pending:
            current_identity = pending.pop()
            if current_identity == source:
                raise ValueError("Policy REQUIRES relation would create a dependency cycle")
            if current_identity in visited:
                continue
            visited.add(current_identity)
            if len(visited) > _MAX_REQUIREMENT_NODES:
                raise ValueError(
                    "Policy requirement cycle check exceeds the 1000-node limit"
                )
            pending.extend(sorted(adjacency.get(current_identity, ()), reverse=True))


__all__ = ["validate_policy_relations"]
