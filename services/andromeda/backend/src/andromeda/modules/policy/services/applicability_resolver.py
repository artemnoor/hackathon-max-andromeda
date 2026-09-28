"""Bitemporal, admission-cycle-aware candidate resolution with mandatory trace."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from andromeda.modules.admissions.contracts.admission_cycles import (
    AdmissionCycle,
    AdmissionCycleResolutionStatus,
    AdmissionCycleState,
)
from andromeda.modules.policy.contracts.applicability import (
    PolicyApplicabilityContext,
    PolicyApplicabilityReason,
    PolicyApplicabilityStatus,
    PolicyContextAvailability,
    PolicyContextOrigin,
    PolicyContextValue,
    PolicyScopeAssessment,
    PolicyScopeMatchState,
    PolicySelection,
    SelectorNodeTrace,
)
from andromeda.modules.policy.contracts.approval import (
    ApprovedPolicyRevision,
    PolicyApprovalEventReference,
    policy_approval_event_reference,
)
from andromeda.modules.policy.contracts.resolution import (
    ConsideredPolicyRule,
    PolicyResolutionBlocker,
    PolicyResolutionMode,
    PolicyResolutionRequest,
    PolicyResolutionStatus,
    PolicyRuleFilterReason,
    PolicyRuleFilterState,
    ResolutionTrace,
    ResolutionTraceFields,
    policy_resolution_trace_id,
)
from andromeda.modules.policy.contracts.rule import (
    PolicyRevisionLifecycle,
    PolicyRuleRevision,
)
from andromeda.modules.policy.domain.applicability import assess_policy_scope
from andromeda.modules.policy.repository.ports import PolicyApprovedSnapshotReader
from andromeda.modules.policy.services.applicability import PolicyApplicabilityService
from andromeda.modules.policy.services.ports import (
    PolicyAdmissionCycleReader,
    PolicyClock,
    PolicyDomainRuleReader,
)


class EffectiveRuleCandidateResolver:
    """Resolve approved candidates for one explicit cycle/time request.

    The result is deliberately a candidate set rather than a final effective
    policy set. Authority, scope precedence, exceptions and conflicts belong to
    the following resolver tasks.
    """

    def __init__(
        self,
        *,
        policies: PolicyApprovedSnapshotReader,
        admission_cycles: PolicyAdmissionCycleReader,
        domain_readers: tuple[PolicyDomainRuleReader, ...],
        clock: PolicyClock,
    ) -> None:
        self._policies = policies
        self._admission_cycles = admission_cycles
        self._clock = clock
        self._applicability = PolicyApplicabilityService(
            domain_readers=domain_readers,
        )

    def resolve(self, request: PolicyResolutionRequest) -> ResolutionTrace:
        as_known_at = request.as_known_at or self._clock.now()
        if as_known_at.tzinfo is None or as_known_at.utcoffset() is None:
            raise ValueError("policy clock must return an aware datetime")
        as_known_at = as_known_at.astimezone(UTC)
        approved_revisions = tuple(
            sorted(
                self._policies.list_approved_revision_records(
                    as_known_at=as_known_at
                ),
                key=lambda item: (
                    item.revision.rule_id,
                    item.revision.revision,
                    item.revision.content_hash,
                ),
            )
        )
        return self.resolve_approved_snapshot(
            request,
            approved_revisions=approved_revisions,
            as_known_at=as_known_at,
        )

    def resolve_approved_snapshot(
        self,
        request: PolicyResolutionRequest,
        *,
        approved_revisions: tuple[ApprovedPolicyRevision, ...],
        as_known_at: datetime,
    ) -> ResolutionTrace:
        """Evaluate one exact snapshot already filtered by the approved read port."""

        if as_known_at.tzinfo is None or as_known_at.utcoffset() is None:
            raise ValueError("approved snapshot time must be timezone-aware")
        snapshot = tuple(
            sorted(
                approved_revisions,
                key=lambda item: (
                    item.revision.rule_id,
                    item.revision.revision,
                    item.revision.content_hash,
                ),
            )
        )
        revisions = tuple(item.revision for item in snapshot)
        self._validate_unique_revision_identities(revisions)
        return self._resolve_snapshot(
            request,
            revisions=revisions,
            approval_references=_approval_references(snapshot),
            as_known_at=as_known_at.astimezone(UTC),
        )

    def resolve_hypothetical_snapshot(
        self,
        request: PolicyResolutionRequest,
        *,
        approved_revisions: tuple[ApprovedPolicyRevision, ...],
        candidate_revision: PolicyRuleRevision,
        as_known_at: datetime,
    ) -> ResolutionTrace:
        """Build a candidate trace from an immutable approved snapshot plus one overlay.

        This method never persists or approves the overlay. The returned trace is
        explicitly marked hypothetical and is not used by EffectivePolicyResolver.
        """

        if as_known_at.tzinfo is None or as_known_at.utcoffset() is None:
            raise ValueError("hypothetical preview time must be timezone-aware")
        normalized_time = as_known_at.astimezone(UTC)
        candidate_identity = (
            candidate_revision.rule_id,
            candidate_revision.revision,
        )
        revisions = tuple(item.revision for item in approved_revisions)
        if any(
            (item.rule_id, item.revision) == candidate_identity
            for item in revisions
        ):
            raise ValueError(
                "hypothetical candidate cannot replace an approved revision identity"
            )
        revisions = tuple(
            sorted(
                (*revisions, candidate_revision),
                key=lambda item: (item.rule_id, item.revision, item.content_hash),
            )
        )
        return self._resolve_snapshot(
            request,
            revisions=revisions,
            approval_references=_approval_references(approved_revisions),
            as_known_at=normalized_time,
            hypothetical_revision=candidate_revision,
        )

    def _resolve_snapshot(
        self,
        request: PolicyResolutionRequest,
        *,
        revisions: tuple[PolicyRuleRevision, ...],
        approval_references: dict[
            tuple[str, int, str], PolicyApprovalEventReference
        ],
        as_known_at: datetime,
        hypothetical_revision: PolicyRuleRevision | None = None,
    ) -> ResolutionTrace:
        cycle_result = self._admission_cycles.resolve_for_admission(
            request.university_id,
            request.admission_year,
            as_known_at=as_known_at,
        )
        cycle = (
            cycle_result.cycle
            if cycle_result.status is AdmissionCycleResolutionStatus.RESOLVED
            else None
        )
        blockers = self._request_blockers(request, cycle)
        context = self._build_context(request.context, cycle)
        considered = tuple(
            self._consider_revision(
                revision,
                context=context,
                request=request,
                as_known_at=as_known_at,
                blockers=blockers,
                approval_event=approval_references.get(
                    (revision.rule_id, revision.revision, revision.content_hash)
                ),
            )
            for revision in revisions
        )
        status = self._trace_status(blockers, considered)
        candidates = tuple(
            item.selection
            for item in considered
            if item.filter_state is PolicyRuleFilterState.CANDIDATE
            and item.selection is not None
        )
        fields = ResolutionTraceFields(
            university_id=request.university_id,
            admission_year=request.admission_year,
            cycle_id=cycle.cycle_id if cycle else None,
            cycle_revision=cycle.revision if cycle else None,
            cycle_evidence=cycle.evidence if cycle else (),
            valid_as_of=request.valid_as_of,
            as_known_at=as_known_at,
            context_fingerprint=_context_fingerprint(context),
            mode=(
                PolicyResolutionMode.HYPOTHETICAL
                if hypothetical_revision is not None
                else PolicyResolutionMode.APPROVED_EFFECTIVE
            ),
            status=status,
            blockers=blockers,
            considered=considered,
            candidates=candidates,
        )
        return ResolutionTrace(
            **fields.model_dump(mode="python"),
            trace_id=policy_resolution_trace_id(fields),
        )

    def _consider_revision(
        self,
        revision: PolicyRuleRevision,
        *,
        context: PolicyApplicabilityContext,
        request: PolicyResolutionRequest,
        as_known_at: datetime,
        blockers: tuple[PolicyResolutionBlocker, ...],
        approval_event: PolicyApprovalEventReference | None,
    ) -> ConsideredPolicyRule:
        valid_interval = revision.temporal.clock.valid_time
        effective_interval = revision.temporal.source_milestones.effective_time
        if blockers:
            return _considered(
                revision,
                PolicyRuleFilterState.BLOCKED,
                PolicyRuleFilterReason.VALID_AS_OF_MISSING
                if PolicyResolutionBlocker.VALID_AS_OF_REQUIRED in blockers
                else (
                    PolicyRuleFilterReason.ADMISSION_CYCLE_UNRESOLVED
                    if PolicyResolutionBlocker.ADMISSION_CYCLE_UNRESOLVED in blockers
                else PolicyRuleFilterReason.ADMISSION_CYCLE_BLOCKED
                ),
                approval_event=approval_event,
            )
        if request.valid_as_of is None:
            return _considered(
                revision,
                PolicyRuleFilterState.BLOCKED,
                PolicyRuleFilterReason.VALID_AS_OF_MISSING,
                approval_event=approval_event,
            )
        if revision.lifecycle not in {
            PolicyRevisionLifecycle.EFFECTIVE,
            PolicyRevisionLifecycle.FUTURE_EFFECTIVE,
        }:
            return _considered(
                revision,
                PolicyRuleFilterState.NOT_APPLICABLE,
                PolicyRuleFilterReason.LIFECYCLE_NOT_APPLICABLE,
                approval_event=approval_event,
            )
        if valid_interval is None:
            return _considered(
                revision,
                PolicyRuleFilterState.INDETERMINATE,
                PolicyRuleFilterReason.VALID_TIME_MISSING,
                approval_event=approval_event,
            )
        if not valid_interval.contains(request.valid_as_of):
            return _considered(
                revision,
                PolicyRuleFilterState.NOT_APPLICABLE,
                PolicyRuleFilterReason.OUTSIDE_VALID_TIME,
                approval_event=approval_event,
            )
        if effective_interval is None:
            return _considered(
                revision,
                PolicyRuleFilterState.INDETERMINATE,
                PolicyRuleFilterReason.EFFECTIVE_TIME_MISSING,
                approval_event=approval_event,
            )
        if (
            effective_interval.start is not None
            and request.valid_as_of < effective_interval.start
        ):
            return _considered(
                revision,
                PolicyRuleFilterState.FUTURE,
                PolicyRuleFilterReason.FUTURE_EFFECTIVE,
                approval_event=approval_event,
            )
        if (
            effective_interval.end is not None
            and request.valid_as_of >= effective_interval.end
        ):
            return _considered(
                revision,
                PolicyRuleFilterState.EXPIRED,
                PolicyRuleFilterReason.EFFECTIVE_TIME_ENDED,
                approval_event=approval_event,
            )

        scope_assessment = assess_policy_scope(revision.scope, context)
        if scope_assessment.state is PolicyScopeMatchState.NO_MATCH:
            return _considered(
                revision,
                PolicyRuleFilterState.NOT_APPLICABLE,
                PolicyRuleFilterReason.SCOPE_NOT_MATCHED,
                context=context,
                scope_assessment=scope_assessment,
                approval_event=approval_event,
            )
        if scope_assessment.state is PolicyScopeMatchState.INDETERMINATE:
            return _considered(
                revision,
                PolicyRuleFilterState.INDETERMINATE,
                PolicyRuleFilterReason.SCOPE_CONTEXT_UNKNOWN,
                context=context,
                scope_assessment=scope_assessment,
                approval_event=approval_event,
            )

        # The caller supplies either a snapshot from the approved-only read port
        # or that same snapshot with one explicitly labelled hypothetical overlay.
        assessment = self._applicability.assess_exact_revision(
            revision,
            context=context,
        )
        if assessment.status is PolicyApplicabilityStatus.SELECTOR_MATCHED:
            return _considered(
                revision,
                PolicyRuleFilterState.CANDIDATE,
                PolicyRuleFilterReason.SELECTOR_MATCHED,
                context=context,
                scope_assessment=scope_assessment,
                selector_trace=assessment.node_trace,
                selection=assessment.selection,
                approval_event=approval_event,
            )
        if assessment.status is PolicyApplicabilityStatus.SELECTOR_NOT_MATCHED:
            return _considered(
                revision,
                PolicyRuleFilterState.NOT_APPLICABLE,
                PolicyRuleFilterReason.SELECTOR_NOT_MATCHED,
                context=context,
                scope_assessment=scope_assessment,
                selector_trace=assessment.node_trace,
                approval_event=approval_event,
            )
        if assessment.reason is PolicyApplicabilityReason.OWNER_RULE_NOT_FOUND:
            reason = PolicyRuleFilterReason.OWNER_RULE_NOT_FOUND
            state = PolicyRuleFilterState.UNSUPPORTED
        elif assessment.reason is PolicyApplicabilityReason.OWNER_LOOKUP_UNAVAILABLE:
            reason = PolicyRuleFilterReason.OWNER_LOOKUP_UNAVAILABLE
            state = PolicyRuleFilterState.INDETERMINATE
        elif assessment.reason is PolicyApplicabilityReason.OWNER_PORT_NOT_REGISTERED:
            reason = PolicyRuleFilterReason.OWNER_PORT_NOT_REGISTERED
            state = PolicyRuleFilterState.UNSUPPORTED
        elif assessment.reason is PolicyApplicabilityReason.REVISION_HASH_MISMATCH:
            reason = PolicyRuleFilterReason.APPROVAL_STATE_UNRESOLVED
            state = PolicyRuleFilterState.BLOCKED
        else:
            reason = PolicyRuleFilterReason.REQUIRED_CONTEXT_UNKNOWN
            state = PolicyRuleFilterState.INDETERMINATE
        return _considered(
            revision,
            state,
            reason,
            context=context,
            scope_assessment=scope_assessment,
            selector_trace=assessment.node_trace,
            approval_event=approval_event,
        )

    @staticmethod
    def _request_blockers(
        request: PolicyResolutionRequest,
        cycle: AdmissionCycle | None,
    ) -> tuple[PolicyResolutionBlocker, ...]:
        blockers: list[PolicyResolutionBlocker] = []
        if request.valid_as_of is None:
            blockers.append(PolicyResolutionBlocker.VALID_AS_OF_REQUIRED)
        if cycle is None:
            blockers.append(PolicyResolutionBlocker.ADMISSION_CYCLE_UNRESOLVED)
        elif (
            cycle.university_id != request.university_id
            or cycle.admission_year != request.admission_year
        ):
            blockers.append(PolicyResolutionBlocker.ADMISSION_CYCLE_IDENTITY_MISMATCH)
        elif cycle.state in {
            AdmissionCycleState.CANCELLED,
            AdmissionCycleState.UNKNOWN,
        }:
            blockers.append(
                PolicyResolutionBlocker.ADMISSION_CYCLE_CANCELLED_OR_UNKNOWN
            )
        return tuple(blockers)

    @staticmethod
    def _validate_unique_revision_identities(
        revisions: tuple[PolicyRuleRevision, ...],
    ) -> None:
        identities = tuple((item.rule_id, item.revision) for item in revisions)
        if len(identities) != len(set(identities)):
            raise ValueError(
                "resolution snapshot contains duplicate revision identities"
            )

    @staticmethod
    def _build_context(
        supplied: PolicyApplicabilityContext,
        cycle: AdmissionCycle | None,
    ) -> PolicyApplicabilityContext:
        if cycle is None:
            return supplied
        from andromeda.modules.policy.contracts.rule_ast import PolicyContextField

        cycle_values = [
            PolicyContextValue(
                field=PolicyContextField.UNIVERSITY_ID,
                availability=PolicyContextAvailability.PRESENT,
                origin=PolicyContextOrigin.SOURCE_BACKED_CYCLE,
                value=cycle.university_id,
            ),
            PolicyContextValue(
                field=PolicyContextField.ADMISSION_YEAR,
                availability=PolicyContextAvailability.PRESENT,
                origin=PolicyContextOrigin.SOURCE_BACKED_CYCLE,
                value=int(cycle.admission_year),
            ),
            PolicyContextValue(
                field=PolicyContextField.ACADEMIC_YEAR,
                availability=PolicyContextAvailability.PRESENT,
                origin=PolicyContextOrigin.SOURCE_BACKED_CYCLE,
                value=cycle.academic_year,
            ),
            PolicyContextValue(
                field=PolicyContextField.ADMISSION_CYCLE_ID,
                availability=PolicyContextAvailability.PRESENT,
                origin=PolicyContextOrigin.SOURCE_BACKED_CYCLE,
                value=cycle.cycle_id,
            ),
        ]
        for field, window, bound_name in (
            (
                PolicyContextField.APPLICATION_START_DATE,
                cycle.application_period,
                "start_date",
            ),
            (
                PolicyContextField.APPLICATION_END_DATE,
                cycle.application_period,
                "end_date",
            ),
            (
                PolicyContextField.ENROLLMENT_START_DATE,
                cycle.enrollment_period,
                "start_date",
            ),
            (
                PolicyContextField.ENROLLMENT_END_DATE,
                cycle.enrollment_period,
                "end_date",
            ),
        ):
            bound = getattr(window, bound_name) if window is not None else None
            cycle_values.append(
                PolicyContextValue(
                    field=field,
                    availability=(
                        PolicyContextAvailability.PRESENT
                        if bound is not None
                        else PolicyContextAvailability.UNAVAILABLE
                    ),
                    origin=PolicyContextOrigin.SOURCE_BACKED_CYCLE,
                    value=bound.isoformat() if bound is not None else None,
                )
            )
        return PolicyApplicabilityContext(values=(*supplied.values, *cycle_values))

    @staticmethod
    def _trace_status(
        blockers: tuple[PolicyResolutionBlocker, ...],
        considered: tuple[ConsideredPolicyRule, ...],
    ) -> PolicyResolutionStatus:
        if blockers:
            return PolicyResolutionStatus.BLOCKED_BY_MISSING_DATA
        if any(
            item.filter_state
            in {
                PolicyRuleFilterState.INDETERMINATE,
                PolicyRuleFilterState.UNSUPPORTED,
                PolicyRuleFilterState.BLOCKED,
            }
            for item in considered
        ):
            return PolicyResolutionStatus.INDETERMINATE
        if any(
            item.filter_state is PolicyRuleFilterState.CANDIDATE for item in considered
        ):
            return PolicyResolutionStatus.CANDIDATES_FOUND
        if not considered:
            # An empty approved-rule scan is missing knowledge, not proof that no rule exists.
            return PolicyResolutionStatus.INDETERMINATE
        return PolicyResolutionStatus.NO_MATCH


def _considered(
    revision: PolicyRuleRevision,
    filter_state: PolicyRuleFilterState,
    reason: PolicyRuleFilterReason,
    *,
    context: PolicyApplicabilityContext | None = None,
    scope_assessment: PolicyScopeAssessment | None = None,
    selector_trace: tuple[SelectorNodeTrace, ...] = (),
    selection: PolicySelection | None = None,
    approval_event: PolicyApprovalEventReference | None = None,
) -> ConsideredPolicyRule:
    if scope_assessment is None:
        scope_assessment = assess_policy_scope(
            revision.scope,
            context or PolicyApplicabilityContext(),
        )
    valid = revision.temporal.clock.valid_time
    effective = revision.temporal.source_milestones.effective_time
    return ConsideredPolicyRule(
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
        lifecycle=revision.lifecycle,
        valid_interval=(valid.start, valid.end) if valid is not None else (None, None),
        effective_interval=(effective.start, effective.end)
        if effective is not None
        else None,
        domain_rule=revision.domain_rule,
        family_id=revision.family_id,
        authority=revision.authority,
        scope=revision.scope,
        scope_state=scope_assessment.state,
        scope_reason=scope_assessment.reason,
        evidence=revision.evidence,
        approval_event=approval_event,
        filter_state=filter_state,
        reason=reason,
        selector_trace=selector_trace,
        selection=selection,
    )


def _approval_references(
    records: tuple[ApprovedPolicyRevision, ...],
) -> dict[tuple[str, int, str], PolicyApprovalEventReference]:
    return {
        (record.revision.rule_id, record.revision.revision, record.revision.content_hash):
        policy_approval_event_reference(record.approval_event)
        for record in records
    }


def _context_fingerprint(context: PolicyApplicabilityContext) -> str:
    payload = [
        {
            "availability": item.availability.value,
            "field": item.field.value,
            "origin": item.origin.value,
            "value": item.value,
        }
        for item in sorted(context.values, key=lambda value: value.field.value)
    ]
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["EffectiveRuleCandidateResolver"]
