"""Project internal policy/claim contracts into the public response vocabulary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
    AdmissionBenefitPolicyEvaluationStatus,
)
from andromeda.modules.conversation.contracts.assistant import (
    AssistantPolicyAnswer,
    PolicyAnswerStatus,
)
from andromeda.modules.conversation.contracts.public import PolicyQueryFocus
from andromeda.modules.knowledge.contracts.public import (
    Claim,
    ClaimedPolicyStage,
    ClaimReviewState,
    EvidenceRef,
    KnowledgeClaimLookup,
    KnowledgeSourceKind,
    SourceReliabilityTier,
)
from andromeda.modules.policy.contracts.public import (
    ConsideredPolicyRule,
    PolicyCycleComparison,
    PolicyPrecedenceOutcome,
    PolicyPrecedenceReason,
    PolicyResolutionBlocker,
    PolicyResolutionStatus,
    PolicyRuleFilterState,
    PolicyScopeLevel,
    PolicySelection,
    ResolutionTrace,
)
from andromeda.modules.presentation.contracts.knowledge_response import (
    ConsideredRuleView,
    KnowledgeAnswerState,
    KnowledgeResponseSection,
    ResolutionExplanation,
    ResponseActionability,
    ResponseAssertionReviewState,
    ResponseClaimStage,
    ResponseCycleComparison,
    ResponseDiffChangeKind,
    ResponseDiffStatus,
    ResponseEvidenceLocator,
    ResponseEvidenceReference,
    ResponseFact,
    ResponsePolicyDiffEntry,
    ResponseResolutionState,
    ResponseRuleReference,
    ResponseScopeKind,
    ResponseSourceCategory,
    ResponseSourceReliability,
    ResponseUncertainty,
    RuleConflictView,
    RuleDisposition,
    RuleExceptionView,
    SourceAssertionView,
)

_FACT_LABELS = {
    "admission.exam.required_count": "Число обязательных экзаменов",
    "admission.bvi.eligibility": "Применимость БВИ",
    "admission.olympiad.points_100": "100 баллов за олимпиаду",
    "admission.individual_achievement.points": "Баллы за индивидуальное достижение",
}
_SUBJECT_LABELS = {
    "university": "вуз",
    "direction": "направление подготовки",
    "program": "образовательная программа",
    "exam": "экзамен",
    "olympiad": "олимпиада",
    "olympiad_profile": "профиль олимпиады",
    "individual_achievement": "индивидуальное достижение",
    "applicant_category": "категория поступающего",
}
_UNIT_LABELS = {"exam_count": "экзамена", "points": "баллов"}


def project_policy_answer(
    answer: AssistantPolicyAnswer,
    *,
    focus: PolicyQueryFocus,
    as_known_at: datetime | None,
) -> KnowledgeResponseSection:
    """Return only display-safe fields; source assertion and policy state stay separate."""

    claims = answer.source_claims
    trace = answer.resolution_trace
    evidence_by_key: dict[tuple[str, str, str, str], ResponseEvidenceReference] = {}
    assertions = tuple(_source_assertion_view(item, evidence_by_key) for item in claims)
    resolution = _resolution_explanation(trace, evidence_by_key) if trace else None
    cycle_comparison = (
        _cycle_comparison_view(answer.cycle_comparison, evidence_by_key)
        if answer.cycle_comparison is not None
        else None
    )
    evidence = tuple(evidence_by_key[key] for key in sorted(evidence_by_key))
    status = _answer_state(answer.status)
    actionability = _actionability(answer.status, focus)
    uncertainties = _uncertainties(answer.status)
    missing_data = _missing_data(answer, trace)
    known_at: datetime | None
    if trace is not None:
        known_at = trace.as_known_at
    else:
        known_at = as_known_at
    captured = tuple(
        item.claim.source_milestones.captured_at
        for item in claims
        if item.claim.source_milestones.captured_at is not None
    )
    return KnowledgeResponseSection(
        status=status,
        actionability=actionability,
        source_assertions=assertions,
        known_facts=_domain_evaluation_facts(answer),
        affected_scope=_affected_scope(trace),
        exceptions=resolution.exceptions if resolution is not None else (),
        evidence=evidence,
        resolution=resolution,
        cycle_comparison=cycle_comparison,
        uncertainties=uncertainties,
        missing_data=missing_data,
        as_known_at=known_at,
        last_checked=max(captured) if captured else None,
    )


def _source_assertion_view(
    lookup: KnowledgeClaimLookup,
    evidence_by_key: dict[tuple[str, str, str, str], ResponseEvidenceReference],
) -> SourceAssertionView:
    claim = lookup.claim
    milestones = claim.source_milestones
    evidence = tuple(
        _evidence_reference(
            item.evidence,
            source_name=lookup.source_display_name,
            source_kind=lookup.source_kind,
            reliability=lookup.source_reliability,
            published_at=milestones.published_at,
            captured_at=milestones.captured_at,
        )
        for item in claim.evidence
    )
    for item in evidence:
        key = _evidence_key(item)
        evidence_by_key.setdefault(key, item)
    return SourceAssertionView(
        assertion=claim.assertion_text,
        stage=_claim_stage(claim.claimed_stage),
        review_state=_review_state(claim.review_state),
        source_name=lookup.source_display_name,
        source_category=_source_category(lookup.source_kind, lookup.source_reliability),
        reliability=_reliability(lookup.source_reliability),
        asserted_value=_fact_view(claim),
        published_at=milestones.published_at,
        announced_at=milestones.announced_at,
        adopted_at=milestones.adopted_at,
        effective_from=milestones.effective_time.start
        if milestones.effective_time
        else None,
        effective_to=milestones.effective_time.end
        if milestones.effective_time
        else None,
        evidence=evidence,
    )


def _fact_view(claim: Claim) -> ResponseFact | None:
    proposition = claim.proposition
    if proposition is None:
        return None
    raw_value = proposition.value.value
    if isinstance(raw_value, Decimal):
        display_value = format(raw_value, "f")
    elif isinstance(raw_value, datetime):
        display_value = raw_value.isoformat()
    else:
        display_value = str(raw_value)
    return ResponseFact(
        label=_FACT_LABELS.get(proposition.predicate, "Утверждение источника"),
        value=display_value,
        unit=_UNIT_LABELS.get(proposition.unit or ""),
        subject_label=_SUBJECT_LABELS.get(proposition.subject_kind.value),
    )


def _resolution_explanation(
    trace: ResolutionTrace,
    evidence_by_key: dict[tuple[str, str, str, str], ResponseEvidenceReference],
) -> ResolutionExplanation:
    refs_by_key: dict[tuple[str, int, str], ResponseRuleReference] = {}
    effective_keys = {_selection_key(item) for item in trace.effective_rules}
    conflicting_keys = {_selection_key(item) for item in trace.conflicting_rules}
    for considered in trace.considered:
        selection = considered.selection
        identity = (
            (selection.rule_id, selection.revision, selection.revision_hash)
            if selection is not None
            else (considered.rule_id, considered.revision, considered.revision_hash)
        )
        refs_by_key[identity] = _rule_reference(
            considered.rule_id,
            considered.revision,
            considered.revision_hash,
            considered.scope.level,
            considered.scope.scope_id,
        )
        for item in considered.evidence:
            ref = _evidence_reference(item)
            evidence_by_key.setdefault(_evidence_key(ref), ref)
    conflicts: list[RuleConflictView] = []
    exceptions: list[RuleExceptionView] = []
    for decision in trace.precedence_decisions:
        is_conflict = decision.outcome in {
            PolicyPrecedenceOutcome.CONFLICT,
            PolicyPrecedenceOutcome.INDETERMINATE,
        }
        is_exception = decision.reason is PolicyPrecedenceReason.AUTHORIZED_EXCEPTION
        if not is_conflict and not is_exception:
            continue
        pair = (
            refs_by_key[_selection_key(decision.left)],
            refs_by_key[_selection_key(decision.right)],
        )
        references = tuple(_evidence_reference(item) for item in decision.evidence)
        for ref in references:
            evidence_by_key.setdefault(_evidence_key(ref), ref)
        if is_conflict:
            conflicts.append(RuleConflictView(rules=pair, evidence=references))
        if is_exception:
            exceptions.append(
                RuleExceptionView(
                    rules=pair,
                    selected_rule=(
                        refs_by_key[_selection_key(decision.winner)]
                        if decision.winner is not None
                        else None
                    ),
                    evidence=references,
                )
            )
    selected = tuple(
        refs_by_key[_selection_key(item)] for item in trace.effective_rules
    )
    considered_views = tuple(
        ConsideredRuleView(
            rule=refs_by_key[_considered_key(item)],
            disposition=_disposition(
                item.filter_state,
                _considered_key(item) in effective_keys,
                _considered_key(item) in conflicting_keys,
            ),
        )
        for item in trace.considered
    )
    resolution_evidence = tuple(evidence_by_key[key] for key in sorted(evidence_by_key))
    return ResolutionExplanation(
        trace_reference=trace.trace_id,
        trace_version=trace.trace_version,
        state=_resolution_state(trace.status),
        valid_as_of=trace.valid_as_of,
        selected_rules=selected,
        considered_rules=considered_views,
        conflicts=tuple(conflicts),
        exceptions=tuple(exceptions),
        evidence=resolution_evidence,
        blockers=tuple(sorted({_blocker_label(item) for item in trace.blockers})),
    )


def _cycle_comparison_view(
    comparison: PolicyCycleComparison,
    evidence_by_key: dict[tuple[str, str, str, str], ResponseEvidenceReference],
) -> ResponseCycleComparison:
    before = _resolution_explanation(comparison.before_trace, evidence_by_key)
    after = _resolution_explanation(comparison.after_trace, evidence_by_key)
    changes = tuple(
        ResponsePolicyDiffEntry(
            path=item.path,
            kind=ResponseDiffChangeKind(item.kind.value),
            before=item.before,
            after=item.after,
            before_evidence=tuple(
                _evidence_reference(ref) for ref in item.before_evidence
            ),
            after_evidence=tuple(
                _evidence_reference(ref) for ref in item.after_evidence
            ),
            reason_code=item.reason_code,
        )
        for item in comparison.diff.changes
    )
    for change in changes:
        for ref in (*change.before_evidence, *change.after_evidence):
            evidence_by_key.setdefault(_evidence_key(ref), ref)
    return ResponseCycleComparison(
        before_admission_year=comparison.before_trace.admission_year,
        after_admission_year=comparison.after_trace.admission_year,
        before_resolution=before,
        after_resolution=after,
        diff_reference=comparison.diff.diff_id,
        diff_status=ResponseDiffStatus(comparison.diff.status.value),
        changes=changes,
    )


def _affected_scope(trace: ResolutionTrace | None) -> tuple[ResponseRuleReference, ...]:
    if trace is None:
        return ()
    keys = {
        _selection_key(selection)
        for selection in (*trace.effective_rules, *trace.conflicting_rules)
    }
    refs: dict[tuple[str, int, str], ResponseRuleReference] = {}
    for item in trace.considered:
        key = (
            item.rule_id,
            item.revision,
            item.revision_hash,
        )
        if key in keys:
            refs[key] = _rule_reference(
                item.rule_id,
                item.revision,
                item.revision_hash,
                item.scope.level,
                item.scope.scope_id,
            )
    return tuple(refs[key] for key in sorted(refs))


def _evidence_reference(
    evidence: EvidenceRef,
    *,
    source_name: str | None = None,
    source_kind: KnowledgeSourceKind | None = None,
    reliability: SourceReliabilityTier | None = None,
    published_at: datetime | None = None,
    captured_at: datetime | None = None,
) -> ResponseEvidenceReference:
    return ResponseEvidenceReference(
        source_reference=evidence.source_id,
        observation_reference=evidence.source_observation_id,
        snapshot_sha256=evidence.snapshot_sha256,
        url=evidence.source_url,
        locator=ResponseEvidenceLocator(**evidence.locator.model_dump()),
        source_name=source_name,
        source_category=(
            _source_category(source_kind, reliability)
            if source_kind is not None and reliability is not None
            else ResponseSourceCategory.UNKNOWN
        ),
        reliability=_reliability(reliability)
        if reliability is not None
        else ResponseSourceReliability.UNKNOWN,
        published_at=published_at,
        captured_at=captured_at,
    )


def _evidence_key(
    item: ResponseEvidenceReference,
) -> tuple[str, str, str, str]:
    return (
        item.observation_reference,
        item.snapshot_sha256,
        str(item.url),
        item.locator.model_dump_json(),
    )


def _rule_reference(
    rule_id: str,
    revision: int,
    revision_hash: str,
    scope: PolicyScopeLevel,
    scope_id: str | None,
) -> ResponseRuleReference:
    return ResponseRuleReference(
        rule_reference=rule_id,
        revision=revision,
        revision_hash=revision_hash,
        scope_kind=_scope_kind(scope),
        scope_reference=scope_id,
    )


def _scope_kind(scope: PolicyScopeLevel) -> ResponseScopeKind:
    return {
        PolicyScopeLevel.FEDERAL: ResponseScopeKind.FEDERAL,
        PolicyScopeLevel.UNIVERSITY: ResponseScopeKind.UNIVERSITY,
        PolicyScopeLevel.DIRECTION: ResponseScopeKind.DIRECTION,
        PolicyScopeLevel.PROGRAM: ResponseScopeKind.PROGRAM,
        PolicyScopeLevel.ADMISSION_ROUTE: ResponseScopeKind.ADMISSION_ROUTE,
    }.get(scope, ResponseScopeKind.OTHER)


def _disposition(
    state: PolicyRuleFilterState,
    selected: bool,
    conflicting: bool,
) -> RuleDisposition:
    if selected:
        return RuleDisposition.SELECTED
    if conflicting:
        return RuleDisposition.CONFLICT
    return {
        PolicyRuleFilterState.CANDIDATE: RuleDisposition.CONSIDERED,
        PolicyRuleFilterState.NOT_APPLICABLE: RuleDisposition.NOT_APPLICABLE,
        PolicyRuleFilterState.FUTURE: RuleDisposition.FUTURE,
        PolicyRuleFilterState.EXPIRED: RuleDisposition.EXPIRED,
        PolicyRuleFilterState.INDETERMINATE: RuleDisposition.UNRESOLVED,
        PolicyRuleFilterState.UNSUPPORTED: RuleDisposition.UNAVAILABLE,
        PolicyRuleFilterState.BLOCKED: RuleDisposition.INCOMPLETE_DATA,
    }[state]


def _resolution_state(status: PolicyResolutionStatus) -> ResponseResolutionState:
    return {
        PolicyResolutionStatus.RESOLVED: ResponseResolutionState.RESOLVED,
        PolicyResolutionStatus.CONFLICT: ResponseResolutionState.CONFLICT,
        PolicyResolutionStatus.NO_MATCH: ResponseResolutionState.NO_MATCH,
        PolicyResolutionStatus.BLOCKED_BY_MISSING_DATA: ResponseResolutionState.BLOCKED,
        PolicyResolutionStatus.INDETERMINATE: ResponseResolutionState.INDETERMINATE,
        PolicyResolutionStatus.CANDIDATES_FOUND: ResponseResolutionState.CANDIDATES,
    }[status]


def _answer_state(status: PolicyAnswerStatus) -> KnowledgeAnswerState:
    return {
        PolicyAnswerStatus.RESOLVED: KnowledgeAnswerState.POLICY_RESOLVED,
        PolicyAnswerStatus.POLICY_RESOLVED_DOMAIN_RESULT_UNAVAILABLE: KnowledgeAnswerState.INSUFFICIENT_DATA,
        PolicyAnswerStatus.SOURCE_ASSERTIONS_FOUND: KnowledgeAnswerState.SOURCE_ASSERTION,
        PolicyAnswerStatus.REVIEW_REQUIRED: KnowledgeAnswerState.REVIEW_REQUIRED,
        PolicyAnswerStatus.CONFLICT: KnowledgeAnswerState.CONFLICT,
        PolicyAnswerStatus.NO_MATCH: KnowledgeAnswerState.NO_EVIDENCE,
        PolicyAnswerStatus.BLOCKED_BY_MISSING_DATA: KnowledgeAnswerState.INSUFFICIENT_DATA,
        PolicyAnswerStatus.INDETERMINATE: KnowledgeAnswerState.UNCERTAIN,
        PolicyAnswerStatus.OUTSIDE_COVERAGE: KnowledgeAnswerState.OUTSIDE_COVERAGE,
        PolicyAnswerStatus.HISTORICAL_STATE_UNAVAILABLE: KnowledgeAnswerState.HISTORICAL_STATE_UNAVAILABLE,
    }[status]


def _actionability(
    status: PolicyAnswerStatus,
    focus: PolicyQueryFocus,
) -> ResponseActionability:
    if status is PolicyAnswerStatus.BLOCKED_BY_MISSING_DATA:
        return ResponseActionability.BLOCKED_BY_MISSING_DATA
    if status is PolicyAnswerStatus.POLICY_RESOLVED_DOMAIN_RESULT_UNAVAILABLE:
        return ResponseActionability.BLOCKED_BY_MISSING_DATA
    if status in {
        PolicyAnswerStatus.CONFLICT,
        PolicyAnswerStatus.NO_MATCH,
        PolicyAnswerStatus.INDETERMINATE,
        PolicyAnswerStatus.OUTSIDE_COVERAGE,
        PolicyAnswerStatus.HISTORICAL_STATE_UNAVAILABLE,
        PolicyAnswerStatus.REVIEW_REQUIRED,
    }:
        return ResponseActionability.UNCERTAIN
    if focus in {
        PolicyQueryFocus.STATUS,
        PolicyQueryFocus.CHANGE,
        PolicyQueryFocus.HISTORY,
    }:
        return ResponseActionability.INFORMATIONAL
    return ResponseActionability.INFORMATIONAL


def _uncertainties(status: PolicyAnswerStatus) -> tuple[ResponseUncertainty, ...]:
    mapped = {
        PolicyAnswerStatus.POLICY_RESOLVED_DOMAIN_RESULT_UNAVAILABLE: (
            ResponseUncertainty.DOMAIN_RESULT_UNAVAILABLE,
        ),
        PolicyAnswerStatus.REVIEW_REQUIRED: (
            ResponseUncertainty.SOURCE_ASSERTION_NEEDS_REVIEW,
        ),
        PolicyAnswerStatus.CONFLICT: (ResponseUncertainty.POLICY_CONFLICT_UNRESOLVED,),
        PolicyAnswerStatus.NO_MATCH: (ResponseUncertainty.NO_SOURCE_ASSERTION_FOUND,),
        PolicyAnswerStatus.BLOCKED_BY_MISSING_DATA: (
            ResponseUncertainty.SCOPE_UNKNOWN,
        ),
        PolicyAnswerStatus.INDETERMINATE: (
            ResponseUncertainty.SOURCE_ASSERTIONS_DISAGREE,
        ),
        PolicyAnswerStatus.OUTSIDE_COVERAGE: (
            ResponseUncertainty.OUTSIDE_KNOWLEDGE_COVERAGE,
        ),
        PolicyAnswerStatus.HISTORICAL_STATE_UNAVAILABLE: (
            ResponseUncertainty.HISTORICAL_STATE_UNAVAILABLE,
        ),
    }
    return mapped.get(status, ())


def _missing_data(
    answer: AssistantPolicyAnswer,
    trace: ResolutionTrace | None,
) -> tuple[str, ...]:
    values = {_blocker_label(item) for item in trace.blockers} if trace else set()
    if answer.status is PolicyAnswerStatus.POLICY_RESOLVED_DOMAIN_RESULT_UNAVAILABLE:
        values.update(answer.missing_input_codes)
        if not answer.missing_input_codes:
            values.add("domain_result")
    return tuple(sorted(values))


def _domain_evaluation_facts(
    answer: AssistantPolicyAnswer,
) -> tuple[ResponseFact, ...]:
    evaluation = answer.domain_evaluation
    if (
        evaluation is None
        or evaluation.status is not AdmissionBenefitPolicyEvaluationStatus.EVALUATED
        or evaluation.decision is None
    ):
        return ()
    decision = evaluation.decision
    facts: list[ResponseFact] = [
        ResponseFact(
            label="Проверка применимости действующих льготных правил",
            value=_eligibility_label(decision.status.value),
            subject_label=f"{decision.program_id}, приём {decision.admission_year}",
        )
    ]
    if decision.route is not None:
        facts.append(
            ResponseFact(
                label="Подтверждённый маршрут льготы",
                value=_route_label(decision.route.value),
                subject_label=str(decision.program_id),
            )
        )
    if decision.individual_achievement_points is not None:
        facts.append(
            ResponseFact(
                label="Баллы за индивидуальные достижения",
                value=str(decision.individual_achievement_points),
                unit="баллов",
            )
        )
    if decision.effective_competitive_score is not None:
        facts.append(
            ResponseFact(
                label="Расчётный конкурсный балл с учётом подтверждённых правил",
                value=str(decision.effective_competitive_score),
                unit="баллов",
            )
        )
    if decision.eligibility is not None:
        for item in decision.eligibility.evaluations:
            facts.append(
                ResponseFact(
                    label=f"{_benefit_label(item.benefit_type.value)} по правилу {item.rule_id}",
                    value=_eligibility_label(item.status.value),
                )
            )
    return tuple(facts[:100])


def _eligibility_label(value: str) -> str:
    return {
        "eligible": "подтверждено по указанным фактам",
        "not_eligible": "не применено при подтверждённом полном наборе фактов",
        "insufficient_data": "недостаточно данных",
        "review_required": "требуется проверка",
    }.get(value, "не определено")


def _route_label(value: str) -> str:
    return {
        "olympiad": "олимпиадный маршрут",
        "vosh": "маршрут ВсОШ",
        "international": "международная олимпиада",
        "special_right": "специальное право",
        "preferential_right": "преимущественное право",
        "special_quota": "специальная квота",
        "separate_quota": "отдельная квота",
        "targeted": "целевой маршрут",
    }.get(value, value)


def _benefit_label(value: str) -> str:
    return {
        "bvi": "БВИ",
        "one_hundred_points": "100 баллов за олимпиаду",
        "special_right": "специальное право",
        "preferential_right": "преимущественное право",
        "special_quota": "специальная квота",
        "separate_quota": "отдельная квота",
        "targeted_route": "целевой маршрут",
    }.get(value, "льгота")


def _blocker_label(blocker: PolicyResolutionBlocker) -> str:
    if blocker is PolicyResolutionBlocker.VALID_AS_OF_REQUIRED:
        return "valid_time"
    if blocker is PolicyResolutionBlocker.PRECEDENCE_DECISION_LIMIT:
        return "policy_precedence_limit"
    return "admission_cycle"


def _claim_stage(stage: ClaimedPolicyStage) -> ResponseClaimStage:
    if stage in {ClaimedPolicyStage.RUMOR, ClaimedPolicyStage.HYPOTHESIS}:
        return ResponseClaimStage.POSSIBLE
    if stage in {
        ClaimedPolicyStage.PROPOSAL,
        ClaimedPolicyStage.DRAFT,
        ClaimedPolicyStage.UNDER_REVIEW,
    }:
        return ResponseClaimStage.PROPOSAL
    return {
        ClaimedPolicyStage.ANNOUNCED: ResponseClaimStage.ANNOUNCED,
        ClaimedPolicyStage.ADOPTED: ResponseClaimStage.ADOPTED,
        ClaimedPolicyStage.PUBLISHED: ResponseClaimStage.PUBLISHED,
        ClaimedPolicyStage.FUTURE_EFFECTIVE: ResponseClaimStage.FUTURE_EFFECTIVE,
        ClaimedPolicyStage.EFFECTIVE: ResponseClaimStage.EFFECTIVE,
        ClaimedPolicyStage.SUPERSEDED: ResponseClaimStage.SUPERSEDED,
        ClaimedPolicyStage.REPEALED: ResponseClaimStage.REPEALED,
        ClaimedPolicyStage.WITHDRAWN: ResponseClaimStage.WITHDRAWN,
        ClaimedPolicyStage.REJECTED: ResponseClaimStage.REJECTED,
        ClaimedPolicyStage.UNKNOWN: ResponseClaimStage.UNKNOWN,
        ClaimedPolicyStage.RUMOR: ResponseClaimStage.POSSIBLE,
        ClaimedPolicyStage.HYPOTHESIS: ResponseClaimStage.POSSIBLE,
        ClaimedPolicyStage.PROPOSAL: ResponseClaimStage.PROPOSAL,
        ClaimedPolicyStage.DRAFT: ResponseClaimStage.PROPOSAL,
        ClaimedPolicyStage.UNDER_REVIEW: ResponseClaimStage.PROPOSAL,
    }[stage]


def _review_state(state: ClaimReviewState) -> ResponseAssertionReviewState:
    return {
        ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION: ResponseAssertionReviewState.REVIEWED_AS_SOURCE_ASSERTION,
        ClaimReviewState.UNREVIEWED: ResponseAssertionReviewState.NEEDS_REVIEW,
        ClaimReviewState.NEEDS_REVIEW: ResponseAssertionReviewState.NEEDS_REVIEW,
        ClaimReviewState.UNRESOLVED: ResponseAssertionReviewState.UNRESOLVED,
        ClaimReviewState.REJECTED: ResponseAssertionReviewState.UNRESOLVED,
        ClaimReviewState.DUPLICATE: ResponseAssertionReviewState.UNRESOLVED,
    }[state]


def _source_category(
    source_kind: KnowledgeSourceKind | None,
    reliability: SourceReliabilityTier | None,
) -> ResponseSourceCategory:
    if source_kind in {
        KnowledgeSourceKind.NORMATIVE_DOCUMENT,
        KnowledgeSourceKind.OFFICIAL_APPENDIX,
        KnowledgeSourceKind.UNIVERSITY_ORDER,
        KnowledgeSourceKind.UNIVERSITY_ADMISSION_RULES,
    }:
        return ResponseSourceCategory.OFFICIAL_DOCUMENT
    if source_kind is KnowledgeSourceKind.MINISTRY_PUBLICATION:
        return ResponseSourceCategory.REGULATOR
    if source_kind in {
        KnowledgeSourceKind.OFFICIAL_NEWS,
        KnowledgeSourceKind.OFFICIAL_FEED,
        KnowledgeSourceKind.OFFICIAL_API,
    }:
        if reliability is SourceReliabilityTier.OFFICIAL_UNIVERSITY:
            return ResponseSourceCategory.UNIVERSITY
        return ResponseSourceCategory.REGULATOR
    return {
        SourceReliabilityTier.PRIMARY_NORMATIVE: ResponseSourceCategory.OFFICIAL_DOCUMENT,
        SourceReliabilityTier.OFFICIAL_ISSUER: ResponseSourceCategory.REGULATOR,
        SourceReliabilityTier.OFFICIAL_UNIVERSITY: ResponseSourceCategory.UNIVERSITY,
        SourceReliabilityTier.TRUSTED_SECONDARY: ResponseSourceCategory.SECONDARY_MEDIA,
        SourceReliabilityTier.UNVERIFIED_SECONDARY: ResponseSourceCategory.SECONDARY_MEDIA,
        SourceReliabilityTier.COMMUNITY: ResponseSourceCategory.COMMUNITY,
        SourceReliabilityTier.USER_SUPPLIED: ResponseSourceCategory.USER_SUPPLIED,
        SourceReliabilityTier.UNKNOWN: ResponseSourceCategory.UNKNOWN,
        None: ResponseSourceCategory.UNKNOWN,
    }[reliability]


def _reliability(
    reliability: SourceReliabilityTier,
) -> ResponseSourceReliability:
    return {
        SourceReliabilityTier.PRIMARY_NORMATIVE: ResponseSourceReliability.PRIMARY_OFFICIAL,
        SourceReliabilityTier.OFFICIAL_ISSUER: ResponseSourceReliability.OFFICIAL,
        SourceReliabilityTier.OFFICIAL_UNIVERSITY: ResponseSourceReliability.OFFICIAL,
        SourceReliabilityTier.TRUSTED_SECONDARY: ResponseSourceReliability.TRUSTED_SECONDARY,
        SourceReliabilityTier.UNVERIFIED_SECONDARY: ResponseSourceReliability.UNVERIFIED_SECONDARY,
        SourceReliabilityTier.COMMUNITY: ResponseSourceReliability.COMMUNITY,
        SourceReliabilityTier.USER_SUPPLIED: ResponseSourceReliability.USER_SUPPLIED,
        SourceReliabilityTier.UNKNOWN: ResponseSourceReliability.UNKNOWN,
    }[reliability]


def _considered_key(item: ConsideredPolicyRule) -> tuple[str, int, str]:
    return (item.rule_id, item.revision, item.revision_hash)


def _selection_key(selection: PolicySelection) -> tuple[str, int, str]:
    return (selection.rule_id, selection.revision, selection.revision_hash)


__all__ = ["project_policy_answer"]
