"""Deterministic typed diffs for policy revisions before human approval."""

from __future__ import annotations

import json
import logging
from typing import TypeAlias

from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.modules.policy.contracts.applicability import PolicySelection
from andromeda.modules.policy.contracts.approval import PolicyApprovalState
from andromeda.modules.policy.contracts.resolution import (
    PolicyResolutionStatus,
    ResolutionTrace,
)
from andromeda.modules.policy.contracts.rule import PolicyRuleRevision
from andromeda.modules.policy.contracts.semantic_diff import (
    DiffObjectState,
    EffectivePolicyDiffSnapshot,
    PolicyDiffChangeKind,
    PolicyDiffEntry,
    PolicyDiffLayer,
    PolicyDiffStatus,
    PolicyRevisionDiffSnapshot,
    PolicySemanticDiff,
    policy_semantic_diff_id,
)

logger = logging.getLogger("andromeda.modules.policy.services.semantic_diff")
_RevisionProjection: TypeAlias = dict[str, str]


def build_policy_revision_diff(
    *,
    before: PolicyRuleRevision | None,
    after: PolicyRuleRevision | None,
    before_state: DiffObjectState | None = None,
    after_state: DiffObjectState | None = None,
    before_approval: PolicyApprovalState = PolicyApprovalState.NOT_SUBMITTED,
    after_approval: PolicyApprovalState = PolicyApprovalState.PENDING,
    before_normalizer_version: str = "policy-rule.v2",
    after_normalizer_version: str = "policy-rule.v2",
    before_trace_id: str | None = None,
    after_trace_id: str | None = None,
    source_diff_hash: str | None = None,
    domain_owner_changes: tuple[PolicyDiffEntry, ...] = (),
) -> PolicySemanticDiff:
    logger.info(
        "policy_revision_diff_started before_rule=%s after_rule=%s",
        before.rule_id if before else "unknown",
        after.rule_id if after else "unknown",
    )
    resolved_before_state = before_state or (
        DiffObjectState.PRESENT if before is not None else DiffObjectState.UNKNOWN
    )
    resolved_after_state = after_state or (
        DiffObjectState.PRESENT if after is not None else DiffObjectState.UNKNOWN
    )
    if (before is None) == (resolved_before_state is DiffObjectState.PRESENT):
        raise ValueError("before revision presence conflicts with its explicit state")
    if (after is None) == (resolved_after_state is DiffObjectState.PRESENT):
        raise ValueError("after revision presence conflicts with its explicit state")
    if before is None and after is None:
        raise ValueError("a policy diff needs at least one exact revision")
    if any(not item.path.startswith("domain_owner.") for item in domain_owner_changes):
        raise ValueError("domain-owner semantic diff paths must be owner-namespaced")
    if len({item.path for item in domain_owner_changes}) != len(domain_owner_changes):
        raise ValueError("domain-owner semantic diff paths must be unique")

    before_snapshot = _snapshot(
        before,
        approval=before_approval,
        normalizer_version=before_normalizer_version,
    )
    after_snapshot = _snapshot(
        after,
        approval=after_approval,
        normalizer_version=after_normalizer_version,
    )
    uncertainty: list[str] = []
    if DiffObjectState.UNKNOWN in {resolved_before_state, resolved_after_state}:
        uncertainty.append("revision_presence_unknown")

    changes: tuple[PolicyDiffEntry, ...] = ()
    if not uncertainty:
        before_projection = _project_revision(before) if before is not None else {}
        after_projection = _project_revision(after) if after is not None else {}
        if before is not None and after is not None:
            before_projection["approval_state"] = _json(before_approval.value)
            after_projection["approval_state"] = _json(after_approval.value)
            before_projection["normalizer_version"] = _json(before_normalizer_version)
            after_projection["normalizer_version"] = _json(after_normalizer_version)
        paths = sorted(set(before_projection) | set(after_projection))
        entries: list[PolicyDiffEntry] = list(domain_owner_changes)
        for path in paths:
            old = before_projection.get(path)
            new = after_projection.get(path)
            if old == new:
                continue
            kind = (
                PolicyDiffChangeKind.ADDED
                if old is None
                else PolicyDiffChangeKind.REMOVED
                if new is None
                else PolicyDiffChangeKind.CHANGED
            )
            entries.append(
                PolicyDiffEntry(
                    path=path,
                    kind=kind,
                    before=old,
                    after=new,
                    before_evidence=before.evidence if before is not None and old is not None else (),
                    after_evidence=after.evidence if after is not None and new is not None else (),
                    reason_code=(
                        "normalizer_version_changed"
                        if path == "normalizer_version"
                        else "approval_state_changed"
                        if path == "approval_state"
                        else "typed_policy_field_changed"
                    ),
                )
            )
        entries.sort(key=lambda item: item.path)
        changes = tuple(entries)

    status = PolicyDiffStatus.INCOMPLETE if uncertainty else PolicyDiffStatus.COMPLETE
    diff_id = policy_semantic_diff_id(
        layer=PolicyDiffLayer.REVISION,
        status=status,
        before_state=resolved_before_state,
        after_state=resolved_after_state,
        before=before_snapshot,
        after=after_snapshot,
        changes=changes,
        uncertainty_codes=tuple(uncertainty),
        before_trace_id=before_trace_id,
        after_trace_id=after_trace_id,
        source_diff_hash=source_diff_hash,
    )
    diff = PolicySemanticDiff(
        diff_id=diff_id,
        layer=PolicyDiffLayer.REVISION,
        status=status,
        before_state=resolved_before_state,
        after_state=resolved_after_state,
        before=before_snapshot,
        after=after_snapshot,
        changes=changes,
        uncertainty_codes=tuple(uncertainty),
        before_trace_id=before_trace_id,
        after_trace_id=after_trace_id,
        source_diff_hash=source_diff_hash,
    )
    logger.info(
        "policy_revision_diff_completed diff_id=%s status=%s changed_fields=%d",
        diff.diff_id,
        diff.status.value,
        len(diff.changes),
    )
    return diff


def build_effective_policy_diff(
    *,
    before: ResolutionTrace,
    after: ResolutionTrace,
    source_diff_hash: str | None = None,
) -> PolicySemanticDiff:
    logger.info(
        "effective_policy_diff_started before_trace=%s after_trace=%s",
        before.trace_id,
        after.trace_id,
    )
    before_snapshot = _effective_snapshot(before)
    after_snapshot = _effective_snapshot(after)
    uncertainty: list[str] = []
    if any(
        trace.status
        in {
            PolicyResolutionStatus.BLOCKED_BY_MISSING_DATA,
            PolicyResolutionStatus.INDETERMINATE,
        }
        for trace in (before, after)
    ):
        uncertainty.append("resolution_input_or_candidate_incomplete")
    if any(trace.status is PolicyResolutionStatus.CONFLICT for trace in (before, after)):
        uncertainty.append("unresolved_policy_conflict")
    status = (
        PolicyDiffStatus.AMBIGUOUS
        if "unresolved_policy_conflict" in uncertainty
        else PolicyDiffStatus.INCOMPLETE
        if uncertainty
        else PolicyDiffStatus.COMPLETE
    )
    changes: list[PolicyDiffEntry] = []
    if status is PolicyDiffStatus.COMPLETE:
        before_context = _effective_context(before_snapshot)
        after_context = _effective_context(after_snapshot)
        for path in sorted(set(before_context) | set(after_context)):
            old = before_context.get(path)
            new = after_context.get(path)
            if old == new:
                continue
            changes.append(
                _diff_entry(
                    path=path,
                    before=old,
                    after=new,
                    before_evidence=before_snapshot.evidence if old is not None else (),
                    after_evidence=after_snapshot.evidence if new is not None else (),
                    reason_code=(
                        "effective_context_changed"
                        if path.startswith("context.")
                        else "effective_policy_result_changed"
                    ),
                )
            )
        changes.extend(_selection_diff_entries(before, after))
    diff_changes = tuple(changes)
    before_state = DiffObjectState.PRESENT
    after_state = DiffObjectState.PRESENT
    diff_id = policy_semantic_diff_id(
        layer=PolicyDiffLayer.EFFECTIVE_SET,
        status=status,
        before_state=before_state,
        after_state=after_state,
        before=before_snapshot,
        after=after_snapshot,
        changes=diff_changes,
        uncertainty_codes=tuple(uncertainty),
        before_trace_id=before.trace_id,
        after_trace_id=after.trace_id,
        source_diff_hash=source_diff_hash,
    )
    diff = PolicySemanticDiff(
        diff_id=diff_id,
        layer=PolicyDiffLayer.EFFECTIVE_SET,
        status=status,
        before_state=before_state,
        after_state=after_state,
        before=before_snapshot,
        after=after_snapshot,
        changes=diff_changes,
        uncertainty_codes=tuple(uncertainty),
        before_trace_id=before.trace_id,
        after_trace_id=after.trace_id,
        source_diff_hash=source_diff_hash,
    )
    logger.info(
        "effective_policy_diff_completed diff_id=%s status=%s changed_fields=%d",
        diff.diff_id,
        diff.status.value,
        len(diff.changes),
    )
    return diff


def _effective_snapshot(trace: ResolutionTrace) -> EffectivePolicyDiffSnapshot:
    used = {
        (item.rule_id, item.revision, item.revision_hash)
        for item in (*trace.effective_rules, *trace.conflicting_rules)
    }
    evidence_by_key = {
        _evidence_key(evidence): evidence
        for considered in trace.considered
        if considered.selection is not None
        and (considered.rule_id, considered.revision, considered.revision_hash) in used
        for evidence in considered.evidence
    }
    return EffectivePolicyDiffSnapshot(
        trace_id=trace.trace_id,
        university_id=trace.university_id,
        admission_year=trace.admission_year,
        cycle_id=trace.cycle_id,
        cycle_revision=trace.cycle_revision,
        context_fingerprint=trace.context_fingerprint,
        valid_as_of=trace.valid_as_of,
        as_known_at=trace.as_known_at,
        status=trace.status,
        effective_rules=trace.effective_rules,
        conflicting_rules=trace.conflicting_rules,
        evidence=tuple(evidence_by_key[key] for key in sorted(evidence_by_key)),
    )


def _effective_context(snapshot: EffectivePolicyDiffSnapshot) -> dict[str, str]:
    return {
        "context.university_id": _json(snapshot.university_id),
        "context.admission_year": _json(snapshot.admission_year),
        "context.cycle_id": _json(snapshot.cycle_id),
        "context.cycle_revision": _json(snapshot.cycle_revision),
        "context.fingerprint": _json(snapshot.context_fingerprint),
        "context.valid_as_of": _json(snapshot.valid_as_of.isoformat() if snapshot.valid_as_of else None),
        "context.as_known_at": _json(snapshot.as_known_at.isoformat()),
        "resolution_status": _json(snapshot.status.value),
    }


def _selection_diff_entries(
    before: ResolutionTrace,
    after: ResolutionTrace,
) -> tuple[PolicyDiffEntry, ...]:
    before_selections = before.effective_rules or before.conflicting_rules
    after_selections = after.effective_rules or after.conflicting_rules
    before_by_rule = {item.rule_id: item for item in before_selections}
    after_by_rule = {item.rule_id: item for item in after_selections}
    before_evidence = _evidence_by_selection(before)
    after_evidence = _evidence_by_selection(after)
    entries: list[PolicyDiffEntry] = []
    for rule_id in sorted(set(before_by_rule) | set(after_by_rule)):
        old = before_by_rule.get(rule_id)
        new = after_by_rule.get(rule_id)
        old_value = _json(old.model_dump(mode="json")) if old else None
        new_value = _json(new.model_dump(mode="json")) if new else None
        if old_value == new_value:
            continue
        entries.append(
            _diff_entry(
                path=f"effective_rules.{rule_id}",
                before=old_value,
                after=new_value,
                before_evidence=before_evidence.get(_selection_key(old), ()) if old else (),
                after_evidence=after_evidence.get(_selection_key(new), ()) if new else (),
                reason_code="exact_effective_revision_changed",
            )
        )
    return tuple(entries)


def _evidence_by_selection(
    trace: ResolutionTrace,
) -> dict[tuple[str, int, str], tuple[EvidenceRef, ...]]:
    return {
        (item.rule_id, item.revision, item.revision_hash): item.evidence
        for item in trace.considered
        if item.selection is not None
    }


def _selection_key(selection: PolicySelection) -> tuple[str, int, str]:
    return selection.rule_id, selection.revision, selection.revision_hash


def _evidence_key(evidence: EvidenceRef) -> tuple[str, str, str, str]:
    return (
        evidence.source_observation_id,
        evidence.snapshot_sha256,
        str(evidence.source_url),
        evidence.locator.model_dump_json(),
    )


def _diff_entry(
    *,
    path: str,
    before: str | None,
    after: str | None,
    before_evidence: tuple[EvidenceRef, ...],
    after_evidence: tuple[EvidenceRef, ...],
    reason_code: str,
) -> PolicyDiffEntry:
    return PolicyDiffEntry(
        path=path,
        kind=(
            PolicyDiffChangeKind.ADDED
            if before is None
            else PolicyDiffChangeKind.REMOVED
            if after is None
            else PolicyDiffChangeKind.CHANGED
        ),
        before=before,
        after=after,
        before_evidence=before_evidence,
        after_evidence=after_evidence,
        reason_code=reason_code,
    )


def _snapshot(
    revision: PolicyRuleRevision | None,
    *,
    approval: PolicyApprovalState,
    normalizer_version: str,
) -> PolicyRevisionDiffSnapshot | None:
    if revision is None:
        return None
    return PolicyRevisionDiffSnapshot(
        selection=PolicySelection(
            rule_id=revision.rule_id,
            revision=revision.revision,
            revision_hash=revision.content_hash,
            domain_rule=revision.domain_rule,
        ),
        approval_state=approval,
        normalizer_version=normalizer_version,
        evidence=revision.evidence,
    )


def _project_revision(revision: PolicyRuleRevision | None) -> _RevisionProjection:
    if revision is None:
        return {}
    result: _RevisionProjection = {
        "schema_version": revision.schema_version,
        "family_id": _json(revision.family_id),
        "authority": _json(revision.authority.value if revision.authority else None),
        "scope.level": _json(revision.scope.level.value),
        "scope.id": _json(revision.scope.scope_id),
        "domain_rule.owner": _json(revision.domain_rule.owner_module.value),
        "domain_rule.id": _json(revision.domain_rule.canonical_rule_id),
        "domain_rule.revision": _json(revision.domain_rule.owner_revision),
        "lifecycle": _json(revision.lifecycle.value),
        "valid_time": _json(
            revision.temporal.clock.valid_time.model_dump(mode="json")
            if revision.temporal.clock.valid_time
            else None
        ),
        "source_effective_time": _json(
            revision.temporal.source_milestones.effective_time.model_dump(mode="json")
            if revision.temporal.source_milestones.effective_time
            else None
        ),
        "source_milestones": _json(
            revision.temporal.source_milestones.model_dump(mode="json")
        ),
        "source_claims": _json(
            sorted((item.claim_id, item.revision) for item in revision.source_claims)
        ),
    }
    selector = revision.selector
    result["selector.schema_version"] = selector.schema_version
    for node in sorted(selector.nodes, key=lambda item: item.node_id):
        result[f"selector.nodes.{node.node_id}"] = _json(node.model_dump(mode="json"))
    for relation in sorted(
        revision.relations,
        key=lambda item: (
            item.kind.value,
            item.target_rule_id,
            item.target_revision,
            item.target_hash,
        ),
    ):
        key = f"relations.{relation.kind.value}.{relation.target_rule_id}.{relation.target_revision}"
        result[key] = _json(
            {
                "target_hash": relation.target_hash,
                "source_claim": relation.source_claim.model_dump(mode="json"),
                "evidence": relation.evidence.model_dump(mode="json"),
            }
        )
    return result


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


__all__ = ["build_effective_policy_diff", "build_policy_revision_diff"]
