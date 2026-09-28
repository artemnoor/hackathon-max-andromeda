"""Approved-only policy selector assessment and exact owner-rule dispatch."""

from __future__ import annotations

from datetime import datetime

from andromeda.modules.policy.contracts.applicability import (
    PolicyApplicabilityAssessment,
    PolicyApplicabilityContext,
    PolicyApplicabilityReason,
    PolicyApplicabilityStatus,
    PolicyDomainLookupStatus,
    PolicySelection,
    SelectorNodeState,
)
from andromeda.modules.policy.contracts.rule import (
    PolicyRuleId,
    PolicyRuleRevision,
)
from andromeda.modules.policy.domain.applicability import evaluate_policy_selector
from andromeda.modules.policy.repository.ports import ApprovedPolicyRuleReader
from andromeda.modules.policy.services.ports import PolicyDomainRuleReader


class PolicyApplicabilityService:
    """Evaluate approved revisions; expose a separate exact-revision preview seam."""

    def __init__(
        self,
        *,
        approved_revisions: ApprovedPolicyRuleReader | None = None,
        domain_readers: tuple[PolicyDomainRuleReader, ...],
    ) -> None:
        self._approved_revisions = approved_revisions
        readers_by_owner = {reader.owner_module: reader for reader in domain_readers}
        if len(readers_by_owner) != len(domain_readers):
            raise ValueError(
                "policy domain rule readers must have unique owner modules"
            )
        self._domain_readers = readers_by_owner

    def assess_approved_revision(
        self,
        *,
        rule_id: PolicyRuleId,
        revision: int,
        revision_hash: str,
        context: PolicyApplicabilityContext,
        as_known_at: datetime | None = None,
    ) -> PolicyApplicabilityAssessment:
        revision_record = (
            self._approved_revisions.get_approved_revision(
                rule_id,
                revision,
                as_known_at=as_known_at,
            )
            if self._approved_revisions is not None
            else None
        )
        if revision_record is None:
            return self._empty_assessment(
                rule_id=rule_id,
                revision=revision,
                revision_hash=revision_hash,
                status=PolicyApplicabilityStatus.UNAPPROVED,
                reason=PolicyApplicabilityReason.REVISION_NOT_APPROVED,
            )
        if revision_record.content_hash != revision_hash:
            return self._empty_assessment(
                rule_id=rule_id,
                revision=revision,
                revision_hash=revision_hash,
                status=PolicyApplicabilityStatus.UNAPPROVED,
                reason=PolicyApplicabilityReason.REVISION_HASH_MISMATCH,
            )

        return self.assess_exact_revision(revision_record, context=context)

    def assess_exact_revision(
        self,
        revision_record: PolicyRuleRevision,
        *,
        context: PolicyApplicabilityContext,
    ) -> PolicyApplicabilityAssessment:
        """Evaluate one supplied exact revision without asserting approval.

        This is for isolated hypothetical previews only. Canonical resolver paths
        must continue through ``assess_approved_revision``.
        """

        rule_id = revision_record.rule_id
        revision = revision_record.revision
        revision_hash = revision_record.content_hash

        trace = evaluate_policy_selector(revision_record.selector, context)
        root = next(
            node for node in revision_record.selector.nodes if node.parent_id is None
        )
        root_state = next(item.state for item in trace if item.node_id == root.node_id)
        if root_state is SelectorNodeState.NO_MATCH:
            return PolicyApplicabilityAssessment(
                rule_id=rule_id,
                revision=revision,
                revision_hash=revision_hash,
                status=PolicyApplicabilityStatus.SELECTOR_NOT_MATCHED,
                reason=PolicyApplicabilityReason.SELECTOR_NOT_MATCHED,
                node_trace=trace,
            )
        if root_state is SelectorNodeState.INDETERMINATE:
            return PolicyApplicabilityAssessment(
                rule_id=rule_id,
                revision=revision,
                revision_hash=revision_hash,
                status=PolicyApplicabilityStatus.INDETERMINATE,
                reason=PolicyApplicabilityReason.REQUIRED_CONTEXT_UNKNOWN,
                node_trace=trace,
            )

        reference = revision_record.domain_rule
        reader = self._domain_readers.get(reference.owner_module)
        if reader is None:
            return PolicyApplicabilityAssessment(
                rule_id=rule_id,
                revision=revision,
                revision_hash=revision_hash,
                status=PolicyApplicabilityStatus.UNSUPPORTED,
                reason=PolicyApplicabilityReason.OWNER_PORT_NOT_REGISTERED,
                node_trace=trace,
            )
        owner_lookup = reader.lookup_rule(reference)
        if owner_lookup.requested_reference != reference:
            raise ValueError(
                "policy owner reader returned a result for a different reference"
            )
        if owner_lookup.status is PolicyDomainLookupStatus.UNAVAILABLE:
            return PolicyApplicabilityAssessment(
                rule_id=rule_id,
                revision=revision,
                revision_hash=revision_hash,
                status=PolicyApplicabilityStatus.INDETERMINATE,
                reason=PolicyApplicabilityReason.OWNER_LOOKUP_UNAVAILABLE,
                node_trace=trace,
                domain_lookup=owner_lookup.status,
            )
        if owner_lookup.status is PolicyDomainLookupStatus.NOT_FOUND:
            return PolicyApplicabilityAssessment(
                rule_id=rule_id,
                revision=revision,
                revision_hash=revision_hash,
                status=PolicyApplicabilityStatus.UNSUPPORTED,
                reason=PolicyApplicabilityReason.OWNER_RULE_NOT_FOUND,
                node_trace=trace,
                domain_lookup=owner_lookup.status,
            )
        return PolicyApplicabilityAssessment(
            rule_id=rule_id,
            revision=revision,
            revision_hash=revision_hash,
            status=PolicyApplicabilityStatus.SELECTOR_MATCHED,
            reason=PolicyApplicabilityReason.SELECTOR_MATCHED,
            node_trace=trace,
            selection=PolicySelection(
                rule_id=revision_record.rule_id,
                revision=revision_record.revision,
                revision_hash=revision_record.content_hash,
                domain_rule=reference,
            ),
            domain_lookup=owner_lookup.status,
        )

    @staticmethod
    def _empty_assessment(
        *,
        rule_id: PolicyRuleId,
        revision: int,
        revision_hash: str,
        status: PolicyApplicabilityStatus,
        reason: PolicyApplicabilityReason,
    ) -> PolicyApplicabilityAssessment:
        return PolicyApplicabilityAssessment(
            rule_id=rule_id,
            revision=revision,
            revision_hash=revision_hash,
            status=status,
            reason=reason,
            node_trace=(),
        )


__all__ = ["PolicyApplicabilityService"]
