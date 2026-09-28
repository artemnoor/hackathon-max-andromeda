from __future__ import annotations

from datetime import UTC, datetime

from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.modules.policy.contracts.applicability import (
    PolicyScopeMatchReason,
    PolicyScopeMatchState,
    PolicySelection,
)
from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalEventKind,
    PolicyApprovalEventReference,
    policy_approval_event_id,
)
from andromeda.modules.policy.contracts.dependencies import (
    PolicyDependencyKind,
    PolicyDependencyNode,
    PolicyDependencyNodeKind,
    policy_dependency_edge,
    policy_rule_node,
)
from andromeda.modules.policy.contracts.impact import (
    DomainImpactStatus,
    DomainRuleImpactObservation,
    ImpactActionability,
    ImpactReason,
    PolicyImpactContext,
    PolicyImpactStatus,
)
from andromeda.modules.policy.contracts.resolution import (
    ConsideredPolicyRule,
    PolicyResolutionStatus,
    PolicyRuleFilterReason,
    PolicyRuleFilterState,
    ResolutionTrace,
    ResolutionTraceFields,
    policy_resolution_trace_id,
)
from andromeda.modules.policy.contracts.rule import (
    DomainRuleRef,
    PolicyAuthorityLevel,
    PolicyDomainOwner,
    PolicyRevisionLifecycle,
    PolicyScope,
    PolicyScopeLevel,
)
from andromeda.modules.policy.contracts.semantic_diff import (
    PolicyDiffChangeKind,
    PolicyDiffEntry,
)
from andromeda.modules.policy.services.impact_analyzer import PolicyImpactAnalyzer

NOW = datetime(2028, 9, 1, tzinfo=UTC)
EVIDENCE = EvidenceRef(
    source_id="source:official-rules",
    source_observation_id="source-observation:" + "1" * 32,
    snapshot_sha256="2" * 64,
    source_url="https://official.example/rules.pdf",
)
CONTEXT_HASH = "3" * 64


def _approval_reference(
    rule_id: str, revision: int, revision_hash: str
) -> PolicyApprovalEventReference:
    fingerprint = "c" * 64
    return PolicyApprovalEventReference(
        event_id=policy_approval_event_id(
            rule_id,
            revision,
            2,
            PolicyApprovalEventKind.APPROVED,
            revision_hash,
            preview_fingerprint=fingerprint,
        ),
        rule_id=rule_id,
        revision=revision,
        sequence=2,
        revision_hash=revision_hash,
        recorded_at=NOW,
    )


def _trace(revision: int, owner_revision: int) -> ResolutionTrace:
    owner_ref = DomainRuleRef(
        owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
        canonical_rule_id="admission-benefit:fourth-exam",
        owner_revision=owner_revision,
    )
    selection = PolicySelection(
        rule_id="policy-rule:fourth-exam",
        revision=revision,
        revision_hash=str(revision) * 64,
        domain_rule=owner_ref,
    )
    considered = ConsideredPolicyRule(
        rule_id=selection.rule_id,
        revision=selection.revision,
        revision_hash=selection.revision_hash,
        lifecycle=PolicyRevisionLifecycle.EFFECTIVE,
        valid_interval=(datetime(2028, 1, 1, tzinfo=UTC), None),
        effective_interval=(datetime(2028, 9, 1, tzinfo=UTC), None),
        domain_rule=owner_ref,
        family_id="policy-family:fourth-exam",
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        scope=PolicyScope(level=PolicyScopeLevel.UNIVERSITY, scope_id="university:bmstu"),
        scope_state=PolicyScopeMatchState.MATCH,
        scope_reason=PolicyScopeMatchReason.CONTEXT_MATCHED,
        evidence=(EVIDENCE,),
        approval_event=_approval_reference(
            selection.rule_id, selection.revision, selection.revision_hash
        ),
        filter_state=PolicyRuleFilterState.CANDIDATE,
        reason=PolicyRuleFilterReason.SELECTOR_MATCHED,
        selector_trace=(),
        selection=selection,
    )
    fields = ResolutionTraceFields(
        university_id="university:bmstu",
        admission_year=2028,
        valid_as_of=NOW,
        as_known_at=NOW,
        context_fingerprint=CONTEXT_HASH,
        status=PolicyResolutionStatus.RESOLVED,
        considered=(considered,),
        candidates=(selection,),
        effective_rules=(selection,),
    )
    return ResolutionTrace(
        **fields.model_dump(mode="python"),
        trace_id=policy_resolution_trace_id(fields),
    )


class _BenefitsImpactAdapter:
    owner_module = PolicyDomainOwner.ADMISSION_BENEFITS

    def compare_policy_rules(self, before, after, *, context):
        assert context.context_fingerprint == CONTEXT_HASH
        return DomainRuleImpactObservation(
            owner_module=self.owner_module,
            before_rule=before,
            after_rule=after,
            status=DomainImpactStatus.EVALUATED,
            actionability=ImpactActionability.ACTION_REQUIRED,
            changes=(
                PolicyDiffEntry(
                    path="domain_owner.admission_benefits.benefit_route",
                    kind=PolicyDiffChangeKind.CHANGED,
                    before="bvi",
                    after="100_points",
                    before_evidence=(EVIDENCE,),
                    after_evidence=(EVIDENCE,),
                    reason_code="benefit_owner_semantic_change",
                ),
            ),
            evidence=(EVIDENCE,),
        )


def test_impact_preview_delegates_domain_semantics_and_keeps_trace_evidence() -> None:
    current = _trace(1, 1)
    candidate = _trace(2, 2)
    root_before = policy_rule_node(current.effective_rules[0])
    root_after = policy_rule_node(candidate.effective_rules[0])
    target = PolicyDependencyNode(
        kind=PolicyDependencyNodeKind.SCOPE,
        object_id="program:01.03.02",
    )
    edges = (
        policy_dependency_edge(PolicyDependencyKind.APPLIES_TO, root_before, target, (EVIDENCE,)),
        policy_dependency_edge(PolicyDependencyKind.APPLIES_TO, root_after, target, (EVIDENCE,)),
    )
    context = PolicyImpactContext(
        university_id="university:bmstu",
        admission_year=2028,
        context_fingerprint=CONTEXT_HASH,
    )

    result = PolicyImpactAnalyzer(domain_owners=(_BenefitsImpactAdapter(),)).preview(
        current=current,
        candidate=candidate,
        context=context,
        dependencies=edges,
        calculated_at=NOW,
    )

    assert result.status is PolicyImpactStatus.COMPLETE
    assert result.actionability is ImpactActionability.ACTION_REQUIRED
    assert result.reason is ImpactReason.DOMAIN_OWNER_REQUIRES_ACTION
    assert result.affected_objects[0].node == target
    assert result.affected_objects[0].evidence == (EVIDENCE,)
    assert result.domain_results[0].changes[0].after == "100_points"
    assert result.current_trace_id == current.trace_id
    assert result.candidate_trace_id == candidate.trace_id


def test_impact_preview_blocks_when_domain_owner_adapter_is_missing() -> None:
    current = _trace(1, 1)
    candidate = _trace(2, 2)
    context = PolicyImpactContext(
        university_id="university:bmstu",
        admission_year=2028,
        context_fingerprint=CONTEXT_HASH,
    )

    result = PolicyImpactAnalyzer().preview(
        current=current,
        candidate=candidate,
        context=context,
        dependencies=(),
        calculated_at=NOW,
    )

    assert result.status is PolicyImpactStatus.PARTIAL
    assert result.actionability is ImpactActionability.BLOCKED_BY_MISSING_DATA
    assert result.reason is ImpactReason.DOMAIN_OWNER_RESULT_MISSING
    assert set(result.missing_input_codes) == {
        "domain_owner_admission_benefits_impact_adapter_missing",
        "dependency_edges_unavailable_for_changed_policy",
    }


def test_impact_preview_does_not_cross_contexts_as_if_applicant_impact() -> None:
    current = _trace(1, 1)
    other_context = _trace(2, 2).model_copy(
        update={"context_fingerprint": "4" * 64}
    )
    fields = other_context.model_dump(mode="python", exclude={"trace_id"})
    candidate = ResolutionTrace(
        **fields,
        trace_id=policy_resolution_trace_id(ResolutionTraceFields(**fields)),
    )

    result = PolicyImpactAnalyzer().preview(
        current=current,
        candidate=candidate,
        context=PolicyImpactContext(
            university_id="university:bmstu",
            admission_year=2028,
            context_fingerprint=CONTEXT_HASH,
        ),
        dependencies=(),
        calculated_at=NOW,
    )

    assert result.actionability is ImpactActionability.UNCERTAIN
    assert result.reason is ImpactReason.CONTEXT_MISMATCH
    assert result.status is PolicyImpactStatus.PARTIAL
