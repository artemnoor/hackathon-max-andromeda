"""Deterministic partial ordering for source-approved policy candidates."""

from __future__ import annotations

from enum import StrEnum

from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.modules.policy.contracts.applicability import PolicySelection
from andromeda.modules.policy.contracts.precedence import (
    PolicyPrecedenceDecision,
    PolicyPrecedenceOutcome,
    PolicyPrecedenceReason,
    PolicyPrecedenceResult,
)
from andromeda.modules.policy.contracts.rule import (
    PolicyAuthorityLevel,
    PolicyRuleRelation,
    PolicyRuleRelationKind,
    PolicyRuleRevision,
    PolicyScope,
    PolicyScopeLevel,
)


class ScopeSpecificity(StrEnum):
    EQUAL = "equal"
    LEFT_NARROWER = "left_narrower"
    RIGHT_NARROWER = "right_narrower"
    INCOMPARABLE = "incomparable"


_AUTHORITY_RANK: dict[PolicyAuthorityLevel, int] = {
    PolicyAuthorityLevel.FEDERAL_NORMATIVE: 3,
    PolicyAuthorityLevel.REGULATOR_NORMATIVE: 2,
    PolicyAuthorityLevel.UNIVERSITY_NORMATIVE: 1,
}
_MAX_PRECEDENCE_DECISIONS = 5000

_NARROWER_SCOPE_LEVELS: dict[PolicyScopeLevel, frozenset[PolicyScopeLevel]] = {
    PolicyScopeLevel.FEDERAL: frozenset(
        level for level in PolicyScopeLevel if level is not PolicyScopeLevel.FEDERAL
    ),
    PolicyScopeLevel.UNIVERSITY: frozenset(
        level
        for level in PolicyScopeLevel
        if level
        not in {
            PolicyScopeLevel.FEDERAL,
            PolicyScopeLevel.MINISTRY,
            PolicyScopeLevel.UNIVERSITY,
        }
    ),
    PolicyScopeLevel.FACULTY: frozenset({PolicyScopeLevel.DEPARTMENT}),
    PolicyScopeLevel.DIRECTION: frozenset({PolicyScopeLevel.PROGRAM}),
    PolicyScopeLevel.OLYMPIAD: frozenset({PolicyScopeLevel.OLYMPIAD_PROFILE}),
}


def scope_specificity(left: PolicyScope, right: PolicyScope) -> ScopeSpecificity:
    """Compare only registered hierarchies; orthogonal dimensions stay incomparable."""
    if left.level is right.level and left.scope_id == right.scope_id:
        return ScopeSpecificity.EQUAL
    if right.level in _NARROWER_SCOPE_LEVELS.get(left.level, frozenset()):
        return ScopeSpecificity.RIGHT_NARROWER
    if left.level in _NARROWER_SCOPE_LEVELS.get(right.level, frozenset()):
        return ScopeSpecificity.LEFT_NARROWER
    return ScopeSpecificity.INCOMPARABLE


def resolve_policy_precedence(
    candidates: tuple[PolicyRuleRevision, ...],
) -> PolicyPrecedenceResult:
    """Resolve competing members within reviewer-assigned families, failing closed."""
    ordered = tuple(sorted(candidates, key=_revision_key))
    if any(
        item.family_id is None
        or item.authority is None
        or item.authority is PolicyAuthorityLevel.UNRESOLVED
        for item in ordered
    ):
        return PolicyPrecedenceResult(status="indeterminate")

    selections_by_key = {(_revision_key(item)): _selection(item) for item in ordered}
    decisions: list[PolicyPrecedenceDecision] = []
    effective: list[PolicyRuleRevision] = []
    conflicts: list[PolicyRuleRevision] = []
    indeterminate = False

    family_ids = sorted({item.family_id for item in ordered if item.family_id is not None})
    for family_id in family_ids:
        family = tuple(item for item in ordered if item.family_id == family_id)
        if len(family) == 1:
            effective.append(family[0])
            continue

        directed_wins: dict[tuple[str, int, str], set[tuple[str, int, str]]] = {
            _revision_key(item): set() for item in family
        }
        family_conflict = False
        family_indeterminate = False
        for index, left in enumerate(family):
            for right in family[index + 1 :]:
                if len(decisions) >= _MAX_PRECEDENCE_DECISIONS:
                    return PolicyPrecedenceResult(
                        status="indeterminate",
                        decisions=tuple(decisions),
                        truncated=True,
                    )
                decision = _compare(left, right)
                decisions.append(decision)
                if decision.outcome is PolicyPrecedenceOutcome.LEFT_PREVAILS:
                    directed_wins[_revision_key(left)].add(_revision_key(right))
                elif decision.outcome is PolicyPrecedenceOutcome.RIGHT_PREVAILS:
                    directed_wins[_revision_key(right)].add(_revision_key(left))
                elif decision.outcome is PolicyPrecedenceOutcome.CONFLICT:
                    family_conflict = True
                else:
                    family_indeterminate = True

        if _has_directed_cycle(directed_wins):
            family_conflict = True
            for index, left in enumerate(family):
                for right in family[index + 1 :]:
                    if not any(
                        item.left == selections_by_key[_revision_key(left)]
                        and item.right == selections_by_key[_revision_key(right)]
                        and item.reason is PolicyPrecedenceReason.PRECEDENCE_CYCLE
                        for item in decisions
                    ):
                        if len(decisions) >= _MAX_PRECEDENCE_DECISIONS:
                            return PolicyPrecedenceResult(
                                status="indeterminate",
                                decisions=tuple(decisions),
                                truncated=True,
                            )
                        decisions.append(
                            PolicyPrecedenceDecision(
                                left=selections_by_key[_revision_key(left)],
                                right=selections_by_key[_revision_key(right)],
                                outcome=PolicyPrecedenceOutcome.CONFLICT,
                                reason=PolicyPrecedenceReason.PRECEDENCE_CYCLE,
                                evidence=_unique_evidence((*left.evidence, *right.evidence)),
                            )
                        )

        if family_conflict:
            conflicts.extend(family)
        elif family_indeterminate:
            indeterminate = True
        else:
            winners = tuple(
                item
                for item in family
                if not any(_revision_key(item) in losers for losers in directed_wins.values())
            )
            if len(winners) != 1:
                family_conflict = True
                conflicts.extend(family)
                left, right = family[:2]
                if len(decisions) >= _MAX_PRECEDENCE_DECISIONS:
                    return PolicyPrecedenceResult(
                        status="indeterminate",
                        decisions=tuple(decisions),
                        truncated=True,
                    )
                decisions.append(
                    PolicyPrecedenceDecision(
                        left=selections_by_key[_revision_key(left)],
                        right=selections_by_key[_revision_key(right)],
                        outcome=PolicyPrecedenceOutcome.CONFLICT,
                        reason=PolicyPrecedenceReason.EQUAL_PRECEDENCE,
                        evidence=_unique_evidence((*left.evidence, *right.evidence)),
                    )
                )
            else:
                effective.append(winners[0])

    conflict_selections = tuple(_selection(item) for item in conflicts)
    if conflict_selections:
        return PolicyPrecedenceResult(
            status="conflict",
            conflicting_rules=conflict_selections,
            decisions=tuple(decisions),
        )
    if indeterminate:
        return PolicyPrecedenceResult(status="indeterminate", decisions=tuple(decisions))
    return PolicyPrecedenceResult(
        status="resolved",
        effective_rules=tuple(_selection(item) for item in effective),
        decisions=tuple(decisions),
    )


def _compare(
    left: PolicyRuleRevision,
    right: PolicyRuleRevision,
) -> PolicyPrecedenceDecision:
    left_selection = _selection(left)
    right_selection = _selection(right)
    left_relations = _relations_to(left, right)
    right_relations = _relations_to(right, left)
    evidence = _unique_evidence((*left.evidence, *right.evidence))

    if left_relations and right_relations:
        return _decision(
            left,
            right,
            PolicyPrecedenceOutcome.CONFLICT,
            PolicyPrecedenceReason.AMBIGUOUS_RELATION_SET,
            evidence=evidence,
        )
    if left_relations:
        return _relation_decision(left, right, left, right, left_relations, evidence)
    if right_relations:
        return _relation_decision(left, right, right, left, right_relations, evidence)

    if left.authority is PolicyAuthorityLevel.UNRESOLVED or right.authority is PolicyAuthorityLevel.UNRESOLVED:
        return _decision(
            left,
            right,
            PolicyPrecedenceOutcome.INDETERMINATE,
            PolicyPrecedenceReason.UNRESOLVED_AUTHORITY,
            evidence=evidence,
        )
    specificity = scope_specificity(left.scope, right.scope)
    if specificity is ScopeSpecificity.EQUAL:
        assert left.authority is not None and right.authority is not None
        left_rank = _AUTHORITY_RANK[left.authority]
        right_rank = _AUTHORITY_RANK[right.authority]
        if left_rank > right_rank:
            return _decision(
                left,
                right,
                PolicyPrecedenceOutcome.LEFT_PREVAILS,
                PolicyPrecedenceReason.AUTHORITY,
                winner=left_selection,
                evidence=evidence,
            )
        if right_rank > left_rank:
            return _decision(
                left,
                right,
                PolicyPrecedenceOutcome.RIGHT_PREVAILS,
                PolicyPrecedenceReason.AUTHORITY,
                winner=right_selection,
                evidence=evidence,
            )
        return _decision(
            left,
            right,
            PolicyPrecedenceOutcome.CONFLICT,
            PolicyPrecedenceReason.EQUAL_PRECEDENCE,
            evidence=evidence,
        )

    assert left.authority is not None and right.authority is not None
    if left.authority is right.authority:
        if specificity is ScopeSpecificity.LEFT_NARROWER:
            return _decision(
                left,
                right,
                PolicyPrecedenceOutcome.LEFT_PREVAILS,
                PolicyPrecedenceReason.SPECIFICITY,
                winner=left_selection,
                evidence=evidence,
            )
        if specificity is ScopeSpecificity.RIGHT_NARROWER:
            return _decision(
                left,
                right,
                PolicyPrecedenceOutcome.RIGHT_PREVAILS,
                PolicyPrecedenceReason.SPECIFICITY,
                winner=right_selection,
                evidence=evidence,
            )
        return _decision(
            left,
            right,
            PolicyPrecedenceOutcome.CONFLICT,
            PolicyPrecedenceReason.INCOMPARABLE_SCOPE,
            evidence=evidence,
        )

    return _decision(
        left,
        right,
        PolicyPrecedenceOutcome.CONFLICT,
        PolicyPrecedenceReason.CROSSING_AUTHORITY_AND_SCOPE,
        evidence=evidence,
    )


def _relation_decision(
    pair_left: PolicyRuleRevision,
    pair_right: PolicyRuleRevision,
    source: PolicyRuleRevision,
    target: PolicyRuleRevision,
    relations: tuple[PolicyRuleRelation, ...],
    evidence: tuple[EvidenceRef, ...],
) -> PolicyPrecedenceDecision:
    if len(relations) != 1:
        return _decision(
            pair_left,
            pair_right,
            PolicyPrecedenceOutcome.CONFLICT,
            PolicyPrecedenceReason.AMBIGUOUS_RELATION_SET,
            evidence=evidence,
        )
    relation = relations[0]
    specificity = scope_specificity(source.scope, target.scope)
    if relation.kind is PolicyRuleRelationKind.EXCEPTION_TO:
        return _decision(
            pair_left,
            pair_right,
            PolicyPrecedenceOutcome.CONFLICT,
            PolicyPrecedenceReason.AMBIGUOUS_RELATION_SET,
            relation_kind=relation.kind,
            evidence=(relation.evidence,),
        )
    if relation.kind is PolicyRuleRelationKind.AUTHORIZED_EXCEPTION_TO:
        valid = (
            source.authority is not None
            and target.authority is not None
            and source.authority is not PolicyAuthorityLevel.UNRESOLVED
            and target.authority is not PolicyAuthorityLevel.UNRESOLVED
            and specificity is ScopeSpecificity.LEFT_NARROWER
        )
        reason = PolicyPrecedenceReason.AUTHORIZED_EXCEPTION
    else:
        valid = (
            source.authority is not None
            and target.authority is not None
            and source.authority is not PolicyAuthorityLevel.UNRESOLVED
            and target.authority is not PolicyAuthorityLevel.UNRESOLVED
            and _AUTHORITY_RANK[source.authority] >= _AUTHORITY_RANK[target.authority]
            and specificity in {ScopeSpecificity.EQUAL, ScopeSpecificity.LEFT_NARROWER}
        )
        reason = PolicyPrecedenceReason.EXACT_RELATION
    if not valid:
        return _decision(
            pair_left,
            pair_right,
            PolicyPrecedenceOutcome.CONFLICT,
            PolicyPrecedenceReason.CROSSING_AUTHORITY_AND_SCOPE,
            relation_kind=relation.kind,
            evidence=(relation.evidence,),
        )
    return _decision(
        pair_left,
        pair_right,
        (
            PolicyPrecedenceOutcome.LEFT_PREVAILS
            if source is pair_left
            else PolicyPrecedenceOutcome.RIGHT_PREVAILS
        ),
        reason,
        winner=_selection(source),
        relation_kind=relation.kind,
        evidence=(relation.evidence,),
    )


def _relations_to(
    source: PolicyRuleRevision,
    target: PolicyRuleRevision,
) -> tuple[PolicyRuleRelation, ...]:
    return tuple(
        relation
        for relation in source.relations
        if relation.kind is not PolicyRuleRelationKind.REQUIRES
        if (relation.target_rule_id, relation.target_revision, relation.target_hash)
        == (target.rule_id, target.revision, target.content_hash)
    )


def _decision(
    left: PolicyRuleRevision,
    right: PolicyRuleRevision,
    outcome: PolicyPrecedenceOutcome,
    reason: PolicyPrecedenceReason,
    *,
    winner: PolicySelection | None = None,
    relation_kind: PolicyRuleRelationKind | None = None,
    evidence: tuple[EvidenceRef, ...] = (),
) -> PolicyPrecedenceDecision:
    return PolicyPrecedenceDecision(
        left=_selection(left),
        right=_selection(right),
        outcome=outcome,
        reason=reason,
        winner=winner,
        relation_kind=relation_kind,
        evidence=evidence,
    )


def _has_directed_cycle(graph: dict[tuple[str, int, str], set[tuple[str, int, str]]]) -> bool:
    visiting: set[tuple[str, int, str]] = set()
    visited: set[tuple[str, int, str]] = set()

    def visit(node: tuple[str, int, str]) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(target) for target in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _selection(revision: PolicyRuleRevision) -> PolicySelection:
    return PolicySelection(
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
        domain_rule=revision.domain_rule,
    )


def _revision_key(revision: PolicyRuleRevision) -> tuple[str, int, str]:
    return revision.rule_id, revision.revision, revision.content_hash


def _unique_evidence(items: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    result: list[EvidenceRef] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in items:
        key = (
            item.source_observation_id,
            str(item.source_url),
            item.locator.model_dump_json(),
            item.snapshot_sha256,
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


__all__ = ["ScopeSpecificity", "resolve_policy_precedence", "scope_specificity"]
