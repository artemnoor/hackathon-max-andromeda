"""Read-only hypothetical evaluation for pending policy review revisions."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC

from andromeda.modules.policy.contracts.approval import (
    ApprovedPolicyRevision,
    PolicyApprovalState,
)
from andromeda.modules.policy.contracts.dependencies import (
    dependencies_for_policy_revision,
)
from andromeda.modules.policy.contracts.impact import PolicyImpactContext
from andromeda.modules.policy.contracts.resolution import (
    PolicyResolutionRequest,
    PolicyResolutionStatus,
    ResolutionTrace,
)
from andromeda.modules.policy.contracts.rule import PolicyRuleRevision
from andromeda.modules.policy.contracts.what_if import (
    PolicyHypotheticalPreview,
    PolicyHypotheticalPreviewFields,
    PolicyReviewPreviewTarget,
    policy_hypothetical_preview_id,
)
from andromeda.modules.policy.domain.approval import derive_approval_state
from andromeda.modules.policy.domain.precedence import resolve_policy_precedence
from andromeda.modules.policy.repository.ports import PolicyReviewPreviewReader
from andromeda.modules.policy.services.applicability_resolver import (
    EffectiveRuleCandidateResolver,
)
from andromeda.modules.policy.services.impact_analyzer import PolicyImpactAnalyzer
from andromeda.modules.policy.services.ports import (
    PolicyAdmissionCycleReader,
    PolicyClock,
    PolicyDomainImpactPort,
    PolicyDomainRuleReader,
)
from andromeda.modules.policy.services.resolution_finalizer import (
    apply_precedence_result,
    mark_resolution_indeterminate,
)
from andromeda.modules.policy.services.semantic_diff import (
    build_effective_policy_diff,
)
from andromeda.shared.contracts.errors import ConflictError, NotFoundError

logger = logging.getLogger("andromeda.modules.policy.services.sandbox_evaluator")


class PolicyHypotheticalSandbox:
    """Compare one exact pending revision against one approved snapshot.

    This path is deliberately read-only and never calls EffectivePolicyResolver.
    A hypothetical trace is tagged at the contract level and cannot be confused
    with the approved-effective production trace.
    """

    def __init__(
        self,
        *,
        revisions: PolicyReviewPreviewReader,
        admission_cycles: PolicyAdmissionCycleReader,
        domain_readers: tuple[PolicyDomainRuleReader, ...],
        domain_impact_readers: tuple[PolicyDomainImpactPort, ...],
        clock: PolicyClock,
    ) -> None:
        self._revisions = revisions
        self._admission_cycles = admission_cycles
        self._domain_readers = domain_readers
        self._impact_analyzer = PolicyImpactAnalyzer(
            domain_owners=domain_impact_readers
        )
        self._clock = clock

    def preview(
        self,
        request: PolicyResolutionRequest,
        *,
        rule_id: str,
        revision: int,
        revision_hash: str,
    ) -> PolicyHypotheticalPreview:
        as_known_at = request.as_known_at or self._clock.now()
        if as_known_at.tzinfo is None or as_known_at.utcoffset() is None:
            raise ValueError("hypothetical preview clock must return an aware datetime")
        as_known_at = as_known_at.astimezone(UTC)
        exact_request = request.model_copy(update={"as_known_at": as_known_at})

        candidate_revision = self._revisions.get_revision(rule_id, revision)
        if candidate_revision is None:
            raise NotFoundError("Policy review revision does not exist")
        if candidate_revision.content_hash != revision_hash:
            raise ConflictError(
                "Policy review preview is bound to a stale revision hash"
            )
        events = self._revisions.list_approval_events(
            rule_id,
            revision,
            as_known_at=as_known_at,
        )
        approval_state = derive_approval_state(
            events,
            rule_id=rule_id,
            revision=revision,
            revision_hash=revision_hash,
        )
        if approval_state is not PolicyApprovalState.PENDING:
            raise ConflictError(
                "Only an exact pending policy revision can be previewed"
            )

        approved_snapshot = self._revisions.list_approved_revision_records(
            as_known_at=as_known_at
        )
        try:
            approved_snapshot = tuple(
                ApprovedPolicyRevision.model_validate(
                    item.model_dump(mode="python")
                )
                for item in approved_snapshot
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ConflictError("Approved policy snapshot has invalid approval provenance") from exc
        approved_revisions = tuple(item.revision for item in approved_snapshot)
        approved_snapshot_hash = _snapshot_hash(approved_revisions)
        candidate_resolver = EffectiveRuleCandidateResolver(
            policies=self._revisions,
            admission_cycles=self._admission_cycles,
            domain_readers=self._domain_readers,
            clock=self._clock,
        )
        current_candidates = candidate_resolver.resolve_approved_snapshot(
            exact_request,
            approved_revisions=approved_snapshot,
            as_known_at=as_known_at,
        )
        current_trace = _resolve_precedence(current_candidates, approved_revisions)
        candidate_candidates = candidate_resolver.resolve_hypothetical_snapshot(
            exact_request,
            approved_revisions=approved_snapshot,
            candidate_revision=candidate_revision,
            as_known_at=as_known_at,
        )
        candidate_trace = _resolve_precedence(
            candidate_candidates,
            (*approved_revisions, candidate_revision),
        )

        effective_diff = build_effective_policy_diff(
            before=current_trace,
            after=candidate_trace,
        )
        dependencies = tuple(
            edge
            for item in (*approved_revisions, candidate_revision)
            for edge in dependencies_for_policy_revision(item)
        )
        impact = self._impact_analyzer.preview(
            current=current_trace,
            candidate=candidate_trace,
            context=PolicyImpactContext(
                university_id=exact_request.university_id,
                admission_year=int(exact_request.admission_year),
                context_fingerprint=current_trace.context_fingerprint,
                applicability=exact_request.context,
            ),
            dependencies=dependencies,
            calculated_at=self._clock.now(),
        )
        fields = PolicyHypotheticalPreviewFields(
            target=PolicyReviewPreviewTarget(
                rule_id=rule_id,
                revision=revision,
                revision_hash=revision_hash,
            ),
            approved_snapshot_hash=approved_snapshot_hash,
            current_trace=current_trace,
            candidate_trace=candidate_trace,
            effective_diff=effective_diff,
            impact=impact,
            calculated_at=self._clock.now(),
        )
        preview = PolicyHypotheticalPreview(
            **fields.model_dump(mode="python"),
            preview_id=policy_hypothetical_preview_id(fields),
        )
        logger.info(
            "policy_hypothetical_preview_completed preview_id=%s candidate_rule=%s revision=%d "
            "impact_status=%s actionability=%s",
            preview.preview_id,
            rule_id,
            revision,
            impact.status.value,
            impact.actionability.value,
        )
        return preview


def _resolve_precedence(
    trace: ResolutionTrace,
    revisions: tuple[PolicyRuleRevision, ...],
) -> ResolutionTrace:
    if (
        trace.status is not PolicyResolutionStatus.CANDIDATES_FOUND
        or not trace.candidates
    ):
        return trace
    by_exact_identity = {
        (item.rule_id, item.revision, item.content_hash): item for item in revisions
    }
    selected: list[PolicyRuleRevision] = []
    for reference in trace.candidates:
        exact = by_exact_identity.get(
            (reference.rule_id, reference.revision, reference.revision_hash)
        )
        if exact is None:
            return _indeterminate(trace)
        selected.append(exact)
    return apply_precedence_result(trace, resolve_policy_precedence(tuple(selected)))


def _indeterminate(trace: ResolutionTrace) -> ResolutionTrace:
    return mark_resolution_indeterminate(trace)


def _snapshot_hash(revisions: tuple[PolicyRuleRevision, ...]) -> str:
    identities = tuple(
        (item.rule_id, item.revision, item.content_hash)
        for item in sorted(
            revisions,
            key=lambda value: (value.rule_id, value.revision, value.content_hash),
        )
    )
    canonical = json.dumps(identities, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["PolicyHypotheticalSandbox"]
