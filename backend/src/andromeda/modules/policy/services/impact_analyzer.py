"""Deterministic, bounded current-versus-candidate policy impact preview."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterable
from datetime import datetime

from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.modules.policy.contracts.applicability import PolicySelection
from andromeda.modules.policy.contracts.dependencies import (
    PolicyDependencyEdge,
    PolicyDependencyNode,
    PolicyDependencyNodeKind,
    PolicyDependencyTraversalRequest,
    policy_rule_node,
)
from andromeda.modules.policy.contracts.impact import (
    DomainImpactStatus,
    DomainRuleImpactObservation,
    ImpactActionability,
    ImpactAffectedObject,
    ImpactReason,
    PolicyImpactContext,
    PolicyImpactPreview,
    PolicyImpactPreviewFields,
    PolicyImpactStatus,
    policy_impact_id,
)
from andromeda.modules.policy.contracts.resolution import (
    PolicyResolutionStatus,
    ResolutionTrace,
)
from andromeda.modules.policy.contracts.rule import DomainRuleRef
from andromeda.modules.policy.contracts.semantic_diff import PolicyDiffStatus
from andromeda.modules.policy.domain.dependencies import traverse_policy_dependencies
from andromeda.modules.policy.services.ports import PolicyDomainImpactPort
from andromeda.modules.policy.services.semantic_diff import build_effective_policy_diff

logger = logging.getLogger("andromeda.modules.policy.services.impact_analyzer")
_ACTIONABILITY_RANK = {
    ImpactActionability.NOT_APPLICABLE: 0,
    ImpactActionability.FUTURE_ONLY: 1,
    ImpactActionability.INFORMATIONAL: 2,
    ImpactActionability.ACTION_RECOMMENDED: 3,
    ImpactActionability.ACTION_REQUIRED: 4,
    ImpactActionability.UNCERTAIN: 5,
    ImpactActionability.BLOCKED_BY_MISSING_DATA: 6,
}


class PolicyImpactAnalyzer:
    """Uses resolver traces and delegates all domain meaning to existing owners."""

    def __init__(self, domain_owners: tuple[PolicyDomainImpactPort, ...] = ()) -> None:
        owners = {item.owner_module: item for item in domain_owners}
        if len(owners) != len(domain_owners):
            raise ValueError("only one policy impact adapter may own a domain module")
        self._domain_owners = owners

    def preview(
        self,
        *,
        current: ResolutionTrace,
        candidate: ResolutionTrace,
        context: PolicyImpactContext,
        dependencies: tuple[PolicyDependencyEdge, ...],
        calculated_at: datetime,
    ) -> PolicyImpactPreview:
        logger.info(
            "policy_impact_preview_started current_trace=%s candidate_trace=%s admission_year=%d",
            current.trace_id,
            candidate.trace_id,
            context.admission_year,
        )
        diff = build_effective_policy_diff(before=current, after=candidate)
        missing: list[str] = list(diff.uncertainty_codes)
        reason = ImpactReason.POLICY_CHANGE_INFORMATIONAL
        actionability = ImpactActionability.INFORMATIONAL
        status = PolicyImpactStatus.COMPLETE

        if (
            current.university_id != candidate.university_id
            or current.admission_year != candidate.admission_year
            or current.context_fingerprint != candidate.context_fingerprint
            or current.university_id != context.university_id
            or current.admission_year != context.admission_year
            or current.context_fingerprint != context.context_fingerprint
        ):
            status = PolicyImpactStatus.PARTIAL
            actionability = ImpactActionability.UNCERTAIN
            reason = ImpactReason.CONTEXT_MISMATCH
            missing.append("impact_context_does_not_match_resolution_traces")
        elif current.status is PolicyResolutionStatus.CONFLICT or candidate.status is PolicyResolutionStatus.CONFLICT:
            status = PolicyImpactStatus.PARTIAL
            actionability = ImpactActionability.UNCERTAIN
            reason = ImpactReason.POLICY_CONFLICT
            missing.append("unresolved_policy_conflict")
        elif diff.status is PolicyDiffStatus.INCOMPLETE:
            status = PolicyImpactStatus.PARTIAL
            actionability = ImpactActionability.BLOCKED_BY_MISSING_DATA
            reason = ImpactReason.RESOLUTION_BLOCKED
            missing.append("effective_policy_diff_incomplete")
        elif diff.status is PolicyDiffStatus.AMBIGUOUS:
            status = PolicyImpactStatus.PARTIAL
            actionability = ImpactActionability.UNCERTAIN
            reason = ImpactReason.UNKNOWN_APPLICABILITY
            missing.append("effective_policy_diff_ambiguous")

        changed_selections = _changed_selections(current, candidate)
        dependency_sources = {edge.source.identity() for edge in dependencies}
        missing_dependency_roots = tuple(
            selection
            for selection in changed_selections
            if policy_rule_node(selection).identity() not in dependency_sources
        )
        affected_objects: tuple[ImpactAffectedObject, ...] = ()
        cycles: tuple[str, ...] = ()
        truncated = False
        if status is PolicyImpactStatus.COMPLETE:
            affected_objects, cycles, truncated = self._affected_objects(
                changed_selections,
                dependencies,
            )
            if cycles:
                status = PolicyImpactStatus.PARTIAL
                actionability = ImpactActionability.UNCERTAIN
                reason = ImpactReason.DEPENDENCY_CYCLE
                missing.append("dependency_cycle_detected")
            if truncated:
                status = PolicyImpactStatus.PARTIAL
                actionability = ImpactActionability.UNCERTAIN
                reason = ImpactReason.DEPENDENCY_TRUNCATED
                missing.append("dependency_traversal_truncated")

        domain_results: tuple[DomainRuleImpactObservation, ...] = ()
        if status is PolicyImpactStatus.COMPLETE and changed_selections:
            domain_results, owner_missing = self._evaluate_changed_domain_rules(
                current=current,
                candidate=candidate,
                context=context,
            )
            missing.extend(owner_missing)
            if owner_missing:
                status = PolicyImpactStatus.PARTIAL
                actionability = ImpactActionability.BLOCKED_BY_MISSING_DATA
                reason = ImpactReason.DOMAIN_OWNER_RESULT_MISSING
            elif domain_results:
                owner_actions = tuple(
                    item.actionability
                    for item in domain_results
                    if item.actionability is not None
                )
                if owner_actions:
                    actionability = max(owner_actions, key=_ACTIONABILITY_RANK.__getitem__)
                    reason = _actionability_reason(actionability)
                elif all(
                    item.status is DomainImpactStatus.NO_DOMAIN_CHANGE for item in domain_results
                ):
                    actionability = ImpactActionability.INFORMATIONAL
                    reason = ImpactReason.POLICY_CHANGE_INFORMATIONAL
                else:
                    actionability = ImpactActionability.UNCERTAIN
                    reason = ImpactReason.UNKNOWN_APPLICABILITY
                    status = PolicyImpactStatus.PARTIAL
                    missing.append("domain_owner_actionability_unknown")
        elif status is PolicyImpactStatus.COMPLETE and not changed_selections:
            if _has_future_candidate(candidate) and not current.effective_rules:
                actionability = ImpactActionability.FUTURE_ONLY
                reason = ImpactReason.FUTURE_POLICY_ONLY
            else:
                actionability = ImpactActionability.NOT_APPLICABLE
                reason = ImpactReason.NO_EFFECTIVE_POLICY_CHANGE

        if missing_dependency_roots:
            missing.append("dependency_edges_unavailable_for_changed_policy")
            if (
                status is PolicyImpactStatus.COMPLETE
                and actionability is not ImpactActionability.BLOCKED_BY_MISSING_DATA
            ):
                status = PolicyImpactStatus.PARTIAL
                actionability = ImpactActionability.UNCERTAIN
                reason = ImpactReason.UNKNOWN_APPLICABILITY

        missing_codes = tuple(sorted(set(missing)))
        evidence = _unique_evidence(
            (
                *(diff.before.evidence if diff.before is not None else ()),
                *(diff.after.evidence if diff.after is not None else ()),
                *(reference for result in domain_results for reference in result.evidence),
                *(reference for item in affected_objects for reference in item.evidence),
            )
        )
        fields = PolicyImpactPreviewFields(
            university_id=context.university_id,
            admission_year=context.admission_year,
            context_fingerprint=context.context_fingerprint,
            current_trace_id=current.trace_id,
            candidate_trace_id=candidate.trace_id,
            policy_diff_id=diff.diff_id,
            status=status,
            actionability=actionability,
            reason=reason,
            affected_objects=affected_objects,
            domain_results=domain_results,
            evidence=evidence,
            missing_input_codes=missing_codes,
            dependency_cycles=cycles,
            dependency_truncated=truncated,
            calculated_at=calculated_at,
        )
        impact = PolicyImpactPreview(
            **fields.model_dump(mode="python"),
            impact_id=policy_impact_id(fields),
        )
        logger.info(
            "policy_impact_preview_completed impact_id=%s status=%s actionability=%s "
            "affected_objects=%d missing_inputs=%d",
            impact.impact_id,
            impact.status.value,
            impact.actionability.value,
            len(impact.affected_objects),
            len(impact.missing_input_codes),
        )
        return impact

    def _affected_objects(
        self,
        changed: tuple[PolicySelection, ...],
        dependencies: tuple[PolicyDependencyEdge, ...],
    ) -> tuple[tuple[ImpactAffectedObject, ...], tuple[str, ...], bool]:
        edges_by_source: dict[tuple[str, str, int | None, str | None, str | None], list[PolicyDependencyEdge]] = {}
        edge_by_id = {edge.edge_id: edge for edge in dependencies}
        for edge in dependencies:
            edges_by_source.setdefault(edge.source.identity(), []).append(edge)
        for outgoing in edges_by_source.values():
            outgoing.sort(key=lambda item: item.edge_id)

        affected: dict[
            tuple[str, str, int | None, str | None, str | None],
            tuple[PolicyDependencyNode, tuple[str, ...], tuple[EvidenceRef, ...]],
        ] = {}
        cycles: set[str] = set()
        truncated = False
        for selection in changed:
            root = PolicyDependencyNode(
                kind=PolicyDependencyNodeKind.POLICY_RULE,
                object_id=selection.rule_id,
                revision=selection.revision,
                content_hash=selection.revision_hash,
            )
            traversal = traverse_policy_dependencies(
                PolicyDependencyTraversalRequest(root=root),
                dependencies,
            )
            cycles.update(traversal.cycles)
            truncated = truncated or traversal.truncated
            queue: deque[
                tuple[
                    PolicyDependencyNode,
                    tuple[str, ...],
                    frozenset[tuple[str, str, int | None, str | None, str | None]],
                ]
            ] = deque([(root, (), frozenset({root.identity()}))])
            visited = {root.identity()}
            while queue:
                node, path, ancestors = queue.popleft()
                if len(path) >= 8 and edges_by_source.get(node.identity()):
                    truncated = True
                    continue
                for edge in edges_by_source.get(node.identity(), ()):
                    target_key = edge.target.identity()
                    next_path = (*path, edge.edge_id)
                    if target_key in ancestors:
                        cycles.add(edge.edge_id)
                        continue
                    if target_key not in affected:
                        evidence = _unique_evidence(
                            reference
                            for edge_id in next_path
                            if (path_edge := edge_by_id.get(edge_id)) is not None
                            for reference in path_edge.evidence
                        )
                        affected[target_key] = (edge.target, next_path, evidence)
                        if len(affected) >= 1000:
                            truncated = True
                            break
                    if target_key not in visited:
                        visited.add(target_key)
                        queue.append((edge.target, next_path, ancestors | {target_key}))
                if truncated and len(affected) >= 1000:
                    break
            if len(affected) >= 1000:
                break
        objects = tuple(
            ImpactAffectedObject(node=value[0], relation_path=value[1], evidence=value[2])
            for _, value in sorted(affected.items())
        )
        return objects, tuple(sorted(cycles)), truncated

    def _evaluate_changed_domain_rules(
        self,
        *,
        current: ResolutionTrace,
        candidate: ResolutionTrace,
        context: PolicyImpactContext,
    ) -> tuple[tuple[DomainRuleImpactObservation, ...], tuple[str, ...]]:
        before_rules = _domain_rules(current.effective_rules)
        after_rules = _domain_rules(candidate.effective_rules)
        keys = sorted(set(before_rules) | set(after_rules))
        results: list[DomainRuleImpactObservation] = []
        missing: list[str] = []
        for owner_value, canonical_id in keys[:32]:
            before = before_rules.get((owner_value, canonical_id))
            after = after_rules.get((owner_value, canonical_id))
            if before == after:
                continue
            owner = next(
                item.owner_module
                for item in (*before_rules.values(), *after_rules.values())
                if item.owner_module.value == owner_value
            )
            adapter = self._domain_owners.get(owner)
            if adapter is None:
                code = f"domain_owner_{owner.value}_impact_adapter_missing"
                missing.append(code)
                results.append(
                    DomainRuleImpactObservation(
                        owner_module=owner,
                        before_rule=before,
                        after_rule=after,
                        status=DomainImpactStatus.UNAVAILABLE,
                        actionability=ImpactActionability.BLOCKED_BY_MISSING_DATA,
                        missing_input_codes=(code,),
                    )
                )
                continue
            try:
                result = adapter.compare_policy_rules(before, after, context=context)
            except Exception:
                logger.exception(
                    "policy_domain_impact_adapter_failed owner=%s before_rule=%s after_rule=%s",
                    owner.value,
                    before.canonical_rule_id if before else None,
                    after.canonical_rule_id if after else None,
                )
                code = f"domain_owner_{owner.value}_impact_evaluation_failed"
                missing.append(code)
                results.append(
                    DomainRuleImpactObservation(
                        owner_module=owner,
                        before_rule=before,
                        after_rule=after,
                        status=DomainImpactStatus.UNAVAILABLE,
                        actionability=ImpactActionability.BLOCKED_BY_MISSING_DATA,
                        missing_input_codes=(code,),
                    )
                )
                continue
            if result.owner_module is not owner or result.before_rule != before or result.after_rule != after:
                raise ValueError("domain impact adapter returned a mismatched owner or exact rule reference")
            results.append(result)
            missing.extend(result.missing_input_codes)
        if len(keys) > 32:
            missing.append("domain_rule_comparison_cap_exceeded")
        return tuple(results), tuple(sorted(set(missing)))


def _changed_selections(
    before: ResolutionTrace,
    after: ResolutionTrace,
) -> tuple[PolicySelection, ...]:
    old = {
        (item.rule_id, item.revision, item.revision_hash): item
        for item in before.effective_rules
    }
    new = {
        (item.rule_id, item.revision, item.revision_hash): item
        for item in after.effective_rules
    }
    changed = (*[item for key, item in old.items() if key not in new], *[item for key, item in new.items() if key not in old])
    unique = {(item.rule_id, item.revision, item.revision_hash): item for item in changed}
    return tuple(unique[key] for key in sorted(unique))


def _domain_rules(selections: tuple[PolicySelection, ...]) -> dict[tuple[str, str], DomainRuleRef]:
    result: dict[tuple[str, str], DomainRuleRef] = {}
    for selection in selections:
        reference = selection.domain_rule
        key = reference.owner_module.value, reference.canonical_rule_id
        previous = result.get(key)
        if previous is not None and previous != reference:
            raise ValueError("effective policy set contains conflicting revisions of one domain rule")
        result[key] = reference
    return result


def _has_future_candidate(trace: ResolutionTrace) -> bool:
    return any(item.filter_state.value == "future" for item in trace.considered)


def _unique_evidence(items: Iterable[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    evidence_items = tuple(items)
    unique = {
        (
            item.source_observation_id,
            item.snapshot_sha256,
            str(item.source_url),
            item.locator.model_dump_json(),
        ): item
        for item in evidence_items
    }
    return tuple(unique[key] for key in sorted(unique))


def _actionability_reason(actionability: ImpactActionability) -> ImpactReason:
    return {
        ImpactActionability.ACTION_REQUIRED: ImpactReason.DOMAIN_OWNER_REQUIRES_ACTION,
        ImpactActionability.ACTION_RECOMMENDED: ImpactReason.DOMAIN_OWNER_RECOMMENDS_ACTION,
        ImpactActionability.BLOCKED_BY_MISSING_DATA: ImpactReason.DOMAIN_OWNER_RESULT_MISSING,
        ImpactActionability.UNCERTAIN: ImpactReason.UNKNOWN_APPLICABILITY,
    }.get(actionability, ImpactReason.POLICY_CHANGE_INFORMATIONAL)


__all__ = ["PolicyImpactAnalyzer"]
