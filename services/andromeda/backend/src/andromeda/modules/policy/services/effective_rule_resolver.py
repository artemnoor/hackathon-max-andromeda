"""Final approved-only policy selection after temporal/scope matching."""

from __future__ import annotations

from datetime import UTC, datetime, time

from pydantic import ValidationError

from andromeda.modules.admissions.contracts.admission_cycles import (
    AdmissionCycleResolutionStatus,
)
from andromeda.modules.knowledge.contracts.public import ClaimRevisionRef
from andromeda.modules.policy.contracts.approval import ApprovedPolicyRevision
from andromeda.modules.policy.contracts.public import PolicyCycleComparison
from andromeda.modules.policy.contracts.resolution import (
    PolicyResolutionBlocker,
    PolicyResolutionRequest,
    PolicyResolutionStatus,
    ResolutionTrace,
)
from andromeda.modules.policy.contracts.rule import PolicyRuleRevision
from andromeda.modules.policy.domain.precedence import resolve_policy_precedence
from andromeda.modules.policy.repository.ports import ApprovedPolicyRuleReader
from andromeda.modules.policy.services.applicability_resolver import (
    EffectiveRuleCandidateResolver,
)
from andromeda.modules.policy.services.ports import (
    PolicyAdmissionCycleReader,
    PolicyClock,
    PolicyDomainRuleReader,
)
from andromeda.modules.policy.services.resolution_finalizer import (
    apply_precedence_result,
    mark_resolution_indeterminate,
)
from andromeda.modules.policy.services.semantic_diff import (
    build_effective_policy_diff,
)


class EffectivePolicyResolver:
    """Resolve exact approved revisions and emit only deterministic effective refs."""

    def __init__(
        self,
        *,
        policies: ApprovedPolicyRuleReader,
        admission_cycles: PolicyAdmissionCycleReader,
        domain_readers: tuple[PolicyDomainRuleReader, ...],
        clock: PolicyClock,
    ) -> None:
        self._policies = policies
        self._admission_cycles = admission_cycles
        self._clock = clock
        self._candidate_resolver = EffectiveRuleCandidateResolver(
            policies=policies,
            admission_cycles=admission_cycles,
            domain_readers=domain_readers,
            clock=clock,
        )

    def resolve(self, request: PolicyResolutionRequest) -> ResolutionTrace:
        as_known_at = request.as_known_at or self._clock.now()
        if as_known_at.tzinfo is None or as_known_at.utcoffset() is None:
            raise ValueError("policy clock must return an aware datetime")
        as_known_at = as_known_at.astimezone(UTC)
        approved = self._approved_snapshot(as_known_at)
        if approved is None:
            return self._invalid_approval_trace(request, as_known_at)
        candidate_trace = self._candidate_resolver.resolve_approved_snapshot(
            request, approved_revisions=approved, as_known_at=as_known_at
        )
        return self._resolve_precedence(candidate_trace, approved)

    def resolve_for_claims(
        self,
        request: PolicyResolutionRequest,
        claim_refs: tuple[ClaimRevisionRef, ...],
    ) -> ResolutionTrace:
        """Resolve only approved rules linked to the exact source claim revisions."""

        as_known_at = request.as_known_at or self._clock.now()
        approved = self._approved_snapshot(as_known_at)
        if approved is None:
            return self._invalid_approval_trace(request, as_known_at)
        requested_claims = {(item.claim_id, item.revision) for item in claim_refs}
        linked = tuple(
            record
            for record in approved
            if any(
                (reference.claim_id, reference.revision) in requested_claims
                for reference in record.revision.source_claims
            )
        )
        candidate_trace = self._candidate_resolver.resolve_approved_snapshot(
            request,
            approved_revisions=linked,
            as_known_at=as_known_at,
        )
        return self._resolve_precedence(candidate_trace, linked)

    def resolve_for_admission_cycle(
        self,
        request: PolicyResolutionRequest,
        claim_refs: tuple[ClaimRevisionRef, ...],
    ) -> ResolutionTrace:
        """Resolve at the approved application-window start if no date was asked."""

        exact_request = self._request_for_cycle(request)
        return self.resolve_for_claims(exact_request, claim_refs)

    def compare_for_claims(
        self,
        request: PolicyResolutionRequest,
        admission_years: tuple[int, int],
        claim_refs: tuple[ClaimRevisionRef, ...],
    ) -> PolicyCycleComparison:
        if len(admission_years) != 2 or admission_years[0] >= admission_years[1]:
            raise ValueError("policy comparison requires two ascending admission years")
        as_known_at = request.as_known_at or self._clock.now()
        before_request = self._request_for_cycle(
            request.model_copy(
                update={
                    "admission_year": admission_years[0],
                    "as_known_at": as_known_at,
                }
            )
        )
        after_request = self._request_for_cycle(
            request.model_copy(
                update={
                    "admission_year": admission_years[1],
                    "as_known_at": as_known_at,
                }
            )
        )
        before = self.resolve_for_claims(before_request, claim_refs)
        after = self.resolve_for_claims(after_request, claim_refs)
        diff = build_effective_policy_diff(before=before, after=after)
        return PolicyCycleComparison(
            before_trace=before,
            after_trace=after,
            diff=diff,
        )

    def _request_for_cycle(
        self,
        request: PolicyResolutionRequest,
    ) -> PolicyResolutionRequest:
        as_known_at = request.as_known_at or self._clock.now()
        if request.valid_as_of is not None:
            return request.model_copy(update={"as_known_at": as_known_at})
        cycle_resolution = self._admission_cycles.resolve_for_admission(
            request.university_id,
            request.admission_year,
            as_known_at=as_known_at,
        )
        cycle = (
            cycle_resolution.cycle
            if cycle_resolution.status is AdmissionCycleResolutionStatus.RESOLVED
            else None
        )
        if cycle is None:
            return request.model_copy(update={"as_known_at": as_known_at})
        application_period = cycle.application_period
        if application_period is None:
            return request.model_copy(update={"as_known_at": as_known_at})
        application_start = datetime.combine(
            application_period.start_date,
            time.min,
            tzinfo=UTC,
        )
        return request.model_copy(
            update={"valid_as_of": application_start, "as_known_at": as_known_at}
        )

    def _resolve_precedence(
        self,
        candidate_trace: ResolutionTrace,
        approved: tuple[ApprovedPolicyRevision, ...],
    ) -> ResolutionTrace:
        if (
            candidate_trace.status is not PolicyResolutionStatus.CANDIDATES_FOUND
            or not candidate_trace.candidates
        ):
            return candidate_trace
        by_exact_identity = {
            (item.revision.rule_id, item.revision.revision, item.revision.content_hash): item.revision
            for item in approved
        }
        candidates: list[PolicyRuleRevision] = []
        for selection in candidate_trace.candidates:
            revision = by_exact_identity.get(
                (selection.rule_id, selection.revision, selection.revision_hash)
            )
            if revision is None:
                return mark_resolution_indeterminate(candidate_trace)
            candidates.append(revision)

        result = resolve_policy_precedence(tuple(candidates))
        return apply_precedence_result(candidate_trace, result)

    def _approved_snapshot(
        self, as_known_at: datetime
    ) -> tuple[ApprovedPolicyRevision, ...] | None:
        records = self._policies.list_approved_revision_records(
            as_known_at=as_known_at
        )
        try:
            return tuple(
                ApprovedPolicyRevision.model_validate(
                    item.model_dump(mode="python")
                )
                for item in records
            )
        except (AttributeError, TypeError, ValidationError):
            return None

    def _invalid_approval_trace(
        self,
        request: PolicyResolutionRequest,
        as_known_at: datetime,
    ) -> ResolutionTrace:
        trace = self._candidate_resolver.resolve_approved_snapshot(
            request,
            approved_revisions=(),
            as_known_at=as_known_at,
        )
        return mark_resolution_indeterminate(
            trace,
            blocker=PolicyResolutionBlocker.APPROVAL_PROVENANCE_INVALID,
        )


__all__ = ["EffectivePolicyResolver"]
