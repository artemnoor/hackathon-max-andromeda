from __future__ import annotations

from datetime import UTC, datetime

from pydantic import HttpUrl, TypeAdapter

from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
    AdmissionBenefitPolicyEvaluation,
    AdmissionBenefitPolicyEvaluationStatus,
)
from andromeda.modules.conversation.contracts.assistant import (
    AssistantPolicyAnswer,
    PolicyAnswerStatus,
)
from andromeda.modules.conversation.contracts.public import PolicyQueryFocus
from andromeda.modules.conversation.services.policy_presentation import (
    project_policy_answer,
)
from andromeda.modules.knowledge.contracts.public import EvidenceLocator, EvidenceRef
from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalEventKind,
    PolicyApprovalEventReference,
    policy_approval_event_id,
)
from andromeda.modules.policy.contracts.public import (
    ConsideredPolicyRule,
    DomainRuleRef,
    PolicyAuthorityLevel,
    PolicyCycleComparison,
    PolicyDomainOwner,
    PolicyPrecedenceDecision,
    PolicyPrecedenceOutcome,
    PolicyPrecedenceReason,
    PolicyResolutionStatus,
    PolicyRevisionLifecycle,
    PolicyRuleFilterReason,
    PolicyRuleFilterState,
    PolicyRuleRelationKind,
    PolicyScope,
    PolicyScopeLevel,
    PolicyScopeMatchReason,
    PolicyScopeMatchState,
    PolicySelection,
    ResolutionTrace,
    ResolutionTraceFields,
    policy_resolution_trace_id,
)
from andromeda.modules.policy.services.semantic_diff import (
    build_effective_policy_diff,
)
from andromeda.modules.presentation.contracts.knowledge_response import (
    KnowledgeAnswerState,
    ResponseActionability,
    ResponseScopeKind,
    RuleDisposition,
)
from andromeda.modules.presentation.services.knowledge_response import (
    KnowledgeResponseRenderer,
)

NOW = datetime(2028, 1, 15, tzinfo=UTC)
RULE_HASH = "c" * 64


def _approval_reference(
    rule_id: str, revision: int, revision_hash: str
) -> PolicyApprovalEventReference:
    fingerprint = "a" * 64
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


def _resolved_trace(admission_year: int = 2028) -> ResolutionTrace:
    evidence = EvidenceRef(
        source_id="source:bmstu-admission",
        source_observation_id="source-observation:" + "b" * 32,
        snapshot_sha256="a" * 64,
        source_url=TypeAdapter(HttpUrl).validate_python(
            "https://admissions.bmstu.example/rules.pdf"
        ),
        locator=EvidenceLocator(page=4, section="Поступление"),
    )
    domain_rule = DomainRuleRef(
        owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
        canonical_rule_id="admission-benefit:bvi-test",
        owner_revision=2,
        owner_revision_hash="d" * 64,
    )
    selection = PolicySelection(
        rule_id="policy-rule:bmstu-bvi",
        revision=3,
        revision_hash=RULE_HASH,
        domain_rule=domain_rule,
    )
    federal_domain_rule = DomainRuleRef(
        owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
        canonical_rule_id="admission-benefit:federal-bvi",
        owner_revision=4,
        owner_revision_hash="f" * 64,
    )
    federal_selection = PolicySelection(
        rule_id="policy-rule:federal-bvi",
        revision=2,
        revision_hash="9" * 64,
        domain_rule=federal_domain_rule,
    )

    def considered_rule(
        rule: PolicySelection,
        domain: DomainRuleRef,
        scope: PolicyScope,
        authority: PolicyAuthorityLevel,
        scope_reason: PolicyScopeMatchReason,
    ) -> ConsideredPolicyRule:
        return ConsideredPolicyRule(
            rule_id=rule.rule_id,
            revision=rule.revision,
            revision_hash=rule.revision_hash,
            lifecycle=PolicyRevisionLifecycle.EFFECTIVE,
            valid_interval=(datetime(2027, 1, 1, tzinfo=UTC), None),
            effective_interval=(datetime(2028, 1, 1, tzinfo=UTC), None),
            domain_rule=domain,
            family_id="policy-family:bmstu-bvi",
            authority=authority,
            scope=scope,
            scope_state=PolicyScopeMatchState.MATCH,
            scope_reason=scope_reason,
            evidence=(evidence,),
            approval_event=_approval_reference(
                rule.rule_id, rule.revision, rule.revision_hash
            ),
            filter_state=PolicyRuleFilterState.CANDIDATE,
            reason=PolicyRuleFilterReason.SELECTOR_MATCHED,
            selector_trace=(),
            selection=rule,
        )

    university_scope = PolicyScope(
        level=PolicyScopeLevel.UNIVERSITY,
        scope_id="university:bmstu",
    )
    university_rule = considered_rule(
        selection,
        domain_rule,
        university_scope,
        PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        PolicyScopeMatchReason.CONTEXT_MATCHED,
    )
    federal_rule = considered_rule(
        federal_selection,
        federal_domain_rule,
        PolicyScope(level=PolicyScopeLevel.FEDERAL),
        PolicyAuthorityLevel.FEDERAL_NORMATIVE,
        PolicyScopeMatchReason.FEDERAL_SCOPE,
    )
    precedence = PolicyPrecedenceDecision(
        left=selection,
        right=federal_selection,
        outcome=PolicyPrecedenceOutcome.LEFT_PREVAILS,
        reason=PolicyPrecedenceReason.AUTHORIZED_EXCEPTION,
        winner=selection,
        relation_kind=PolicyRuleRelationKind.AUTHORIZED_EXCEPTION_TO,
        evidence=(evidence,),
    )
    fields = ResolutionTraceFields(
        university_id="university:bmstu",
        admission_year=admission_year,
        valid_as_of=NOW,
        as_known_at=NOW,
        context_fingerprint="e" * 64,
        status=PolicyResolutionStatus.RESOLVED,
        considered=(university_rule, federal_rule),
        candidates=(selection, federal_selection),
        effective_rules=(selection,),
        precedence_decisions=(precedence,),
    )
    return ResolutionTrace(
        **fields.model_dump(mode="python"),
        trace_id=policy_resolution_trace_id(fields),
    )


def test_resolution_projection_keeps_exact_trace_refs_scope_and_evidence() -> None:
    trace = _resolved_trace()
    answer = AssistantPolicyAnswer(
        focus=PolicyQueryFocus.APPLICABILITY,
        status=PolicyAnswerStatus.RESOLVED,
        resolution_trace=trace,
        reason_code="resolved",
    )

    projected = project_policy_answer(
        answer,
        focus=PolicyQueryFocus.APPLICABILITY,
        as_known_at=None,
    )

    assert projected.status is KnowledgeAnswerState.POLICY_RESOLVED
    assert projected.resolution is not None
    assert projected.resolution.trace_reference == trace.trace_id
    assert projected.resolution.selected_rules[0].revision_hash == RULE_HASH
    assert (
        projected.resolution.considered_rules[0].disposition is RuleDisposition.SELECTED
    )
    assert (
        projected.resolution.considered_rules[1].disposition
        is RuleDisposition.CONSIDERED
    )
    assert len(projected.exceptions) == 1
    assert (
        projected.exceptions[0].selected_rule == projected.resolution.selected_rules[0]
    )
    assert projected.affected_scope[0].scope_kind is ResponseScopeKind.UNIVERSITY
    assert projected.affected_scope[0].scope_reference == "university:bmstu"
    assert projected.evidence[0].snapshot_sha256 == "a" * 64
    assert projected.evidence[0].locator.page == 4
    assert projected.as_known_at == NOW


def test_cycle_comparison_projection_keeps_both_resolutions_and_semantic_diff() -> None:
    before = _resolved_trace(2027)
    after = _resolved_trace(2028)
    comparison = PolicyCycleComparison(
        before_trace=before,
        after_trace=after,
        diff=build_effective_policy_diff(before=before, after=after),
    )
    answer = AssistantPolicyAnswer(
        focus=PolicyQueryFocus.HISTORY,
        status=PolicyAnswerStatus.RESOLVED,
        resolution_trace=after,
        cycle_comparison=comparison,
        reason_code="temporal_comparison",
    )

    projected = project_policy_answer(
        answer,
        focus=PolicyQueryFocus.HISTORY,
        as_known_at=NOW,
    )

    assert projected.cycle_comparison is not None
    assert projected.cycle_comparison.before_admission_year == 2027
    assert projected.cycle_comparison.after_admission_year == 2028
    assert (
        projected.cycle_comparison.before_resolution.trace_reference == before.trace_id
    )
    assert projected.cycle_comparison.after_resolution.trace_reference == after.trace_id
    assert projected.cycle_comparison.diff_reference == comparison.diff.diff_id
    assert projected.cycle_comparison.changes
    rendered = KnowledgeResponseRenderer().render(projected)
    assert "2027" in rendered.text and "2028" in rendered.text
    assert "Сравнение правил" in rendered.text


def test_domain_impact_missing_applicant_facts_is_user_visible_as_blocked() -> None:
    missing_code = "applicant_olympiad_achievements_completeness_unconfirmed"
    answer = AssistantPolicyAnswer(
        focus=PolicyQueryFocus.IMPACT,
        status=PolicyAnswerStatus.POLICY_RESOLVED_DOMAIN_RESULT_UNAVAILABLE,
        resolution_trace=_resolved_trace(),
        domain_evaluation=AdmissionBenefitPolicyEvaluation(
            status=AdmissionBenefitPolicyEvaluationStatus.INSUFFICIENT_DATA,
            missing_input_codes=(missing_code,),
        ),
        reason_code=missing_code,
        missing_input_codes=(missing_code,),
    )

    projected = project_policy_answer(
        answer,
        focus=PolicyQueryFocus.IMPACT,
        as_known_at=NOW,
    )

    assert projected.status is KnowledgeAnswerState.INSUFFICIENT_DATA
    assert projected.actionability is ResponseActionability.BLOCKED_BY_MISSING_DATA
    assert projected.missing_data == (missing_code,)
    assert not projected.known_facts
    rendered = KnowledgeResponseRenderer().render(projected).text
    assert "полнота сведений об олимпиадных достижениях не подтверждена" in rendered
    assert missing_code not in rendered
