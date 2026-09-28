"""Targeted refresh for rebuildable projections after approved policy changes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from andromeda.modules.policy.contracts.applicability import PolicySelection
from andromeda.modules.policy.contracts.dependencies import (
    PolicyDependencyNode,
    PolicyDependencyNodeKind,
    domain_rule_node,
    policy_rule_node,
)
from andromeda.modules.policy.contracts.impact import PolicyImpactPreview
from andromeda.modules.policy.contracts.refresh import (
    PolicyProjectionKind,
    PolicyProjectionRefreshCommand,
    PolicyProjectionRefreshRecord,
)
from andromeda.modules.policy.repository.ports import (
    ApprovedPolicyRuleReader,
    PolicyProjectionRefreshRepository,
)
from andromeda.modules.policy.services.ports import PolicyProjectionRefreshBuilder
from andromeda.shared.contracts.errors import ConflictError, ValidationError
from andromeda.shared.contracts.ids import SourceHash

logger = logging.getLogger("andromeda.modules.policy.dependency_refresh")

_MAX_INVALIDATORS = 32
_MAX_REFRESH_TARGETS = 1000
_MAX_BATCH_SIZE = 100


class PolicyDependencyRefreshService:
    """Marks bounded typed targets dirty and rebuilds only those targets."""

    def __init__(
        self,
        *,
        repository: PolicyProjectionRefreshRepository,
        approved_rules: ApprovedPolicyRuleReader,
        builder: PolicyProjectionRefreshBuilder,
    ) -> None:
        self._repository = repository
        self._approved_rules = approved_rules
        self._builder = builder

    def mark_approved_impact_dirty(
        self,
        *,
        impact: PolicyImpactPreview,
        invalidated_by: tuple[PolicySelection, ...],
        invalidated_at: datetime,
    ) -> tuple[PolicyProjectionRefreshRecord, ...]:
        """Mark known affected projections after the canonical approval commit.

        A candidate preview can be inspected without persistence, but this write
        entry point accepts only exact revisions that the approved-only reader
        can resolve. The caller is responsible for invoking it after commit.
        """
        if not invalidated_by or len(invalidated_by) > _MAX_INVALIDATORS:
            raise ValidationError("policy refresh requires 1..32 exact approved invalidators")
        selections = tuple(sorted(invalidated_by, key=_selection_key))
        if len({(item.rule_id, item.revision, item.revision_hash) for item in selections}) != len(selections):
            raise ValidationError("policy refresh invalidators must be unique")
        if invalidated_at.tzinfo is None or invalidated_at.utcoffset() is None:
            raise ValidationError("policy refresh invalidation time must be timezone-aware")

        for selection in selections:
            revision = self._approved_rules.get_approved_revision(
                selection.rule_id,
                selection.revision,
                as_known_at=invalidated_at,
            )
            if revision is None or revision.content_hash != selection.revision_hash:
                raise ConflictError("policy refresh can only target exact approved revisions")

        targets: dict[
            tuple[str, str, int | None, str | None, str | None],
            tuple[PolicyDependencyNode, set[PolicyProjectionKind]],
        ] = {}

        def add_target(node: PolicyDependencyNode, *kinds: PolicyProjectionKind) -> None:
            if node.identity() not in targets:
                targets[node.identity()] = (node, set())
            target_kinds = targets[node.identity()][1]
            target_kinds.update(kinds)

        for selection in selections:
            add_target(
                policy_rule_node(selection),
                PolicyProjectionKind.EFFECTIVE_POLICY,
                PolicyProjectionKind.DEPENDENCY_CLOSURE,
            )
            add_target(
                domain_rule_node(selection.domain_rule),
                PolicyProjectionKind.DOMAIN_IMPACT,
            )
        for affected in impact.affected_objects:
            kinds = _projection_kinds_for(affected.node.kind)
            add_target(affected.node, *kinds)

        if len(targets) > _MAX_REFRESH_TARGETS:
            raise ValidationError("policy refresh target cap exceeded")
        records: list[PolicyProjectionRefreshRecord] = []
        for identity in sorted(targets):
            node, target_kinds = targets[identity]
            for kind in sorted(target_kinds, key=lambda item: item.value):
                command = PolicyProjectionRefreshCommand(
                    target=node,
                    projection_kind=kind,
                    invalidated_by=selections,
                    invalidated_at=invalidated_at,
                )
                records.append(self._repository.mark_dirty(command))
        logger.info(
            "policy_projection_refresh_marked count=%d invalidators=%d impact_id=%s",
            len(records),
            len(selections),
            impact.impact_id,
        )
        return tuple(records)

    def refresh_pending(self, *, limit: int = _MAX_BATCH_SIZE) -> tuple[PolicyProjectionRefreshRecord, ...]:
        """Rebuild a bounded batch; stale generations are rejected by the repository."""
        if not 1 <= limit <= _MAX_BATCH_SIZE:
            raise ValidationError("policy projection refresh batch must be within 1..100")
        results: list[PolicyProjectionRefreshRecord] = []
        for record in self._repository.list_dirty(limit=limit):
            attempted_at = datetime.now(UTC)
            try:
                version = SourceHash(self._builder.rebuild(record))
                result = self._repository.record_success(
                    record.refresh_key,
                    generation=record.generation,
                    projection_version=version,
                    recorded_at=attempted_at,
                )
            except Exception:  # noqa: BLE001 - projection refresh must not undo canonical approval
                logger.warning(
                    "policy_projection_refresh_failed key=%s generation=%d",
                    record.refresh_key,
                    record.generation,
                )
                result = self._repository.record_failure(
                    record.refresh_key,
                    generation=record.generation,
                    failure_code="projection_build_failed",
                    recorded_at=attempted_at,
                )
            results.append(result)
        return tuple(results)


def _selection_key(selection: PolicySelection) -> tuple[str, int, str]:
    return selection.rule_id, selection.revision, selection.revision_hash


def _projection_kinds_for(kind: PolicyDependencyNodeKind) -> tuple[PolicyProjectionKind, ...]:
    if kind is PolicyDependencyNodeKind.POLICY_RULE:
        return (PolicyProjectionKind.EFFECTIVE_POLICY, PolicyProjectionKind.DEPENDENCY_CLOSURE)
    if kind is PolicyDependencyNodeKind.DOMAIN_RULE:
        return (PolicyProjectionKind.DOMAIN_IMPACT,)
    return (PolicyProjectionKind.EFFECTIVE_POLICY,)


__all__ = ["PolicyDependencyRefreshService"]
