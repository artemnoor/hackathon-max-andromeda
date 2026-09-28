from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from andromeda.modules.admissions.contracts.admission_cycles import (
    AdmissionCycle,
    AdmissionCycleResolution,
    AdmissionCycleResolutionStatus,
    AdmissionCycleState,
    InclusiveDateWindow,
)
from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    ClaimRevisionRef,
    EvidenceLocator,
    EvidenceRef,
    SourceMilestones,
    TemporalInterval,
)
from andromeda.modules.policy.contracts.applicability import (
    PolicyApplicabilityContext,
    PolicyApplicabilityReason,
    PolicyApplicabilityStatus,
    PolicyContextAvailability,
    PolicyContextOrigin,
    PolicyContextValue,
    PolicyDomainLookupStatus,
    PolicyDomainRuleLookup,
    PolicyScopeMatchState,
    SelectorNodeReason,
    SelectorNodeState,
)
from andromeda.modules.policy.contracts.approval import (
    ApprovedPolicyRevision,
    PolicyApprovalEventKind,
)
from andromeda.modules.policy.contracts.precedence import (
    PolicyPrecedenceOutcome,
    PolicyPrecedenceReason,
)
from andromeda.modules.policy.contracts.resolution import (
    PolicyResolutionBlocker,
    PolicyResolutionRequest,
    PolicyResolutionStatus,
    PolicyRuleFilterReason,
    PolicyRuleFilterState,
)
from andromeda.modules.policy.contracts.rule import (
    DomainRuleRef,
    PolicyAuthorityLevel,
    PolicyDomainOwner,
    PolicyRevisionLifecycle,
    PolicyRuleRelation,
    PolicyRuleRelationKind,
    PolicyRuleRevision,
    PolicyRuleRevisionFields,
    PolicyScope,
    PolicyScopeLevel,
    policy_rule_content_hash,
)
from andromeda.modules.policy.contracts.rule_ast import (
    PolicyContextField,
    PolicySelectorAst,
    PolicySelectorNode,
    PolicySelectorNodeKind,
)
from andromeda.modules.policy.contracts.temporal import PolicyTemporalRevision
from andromeda.modules.policy.domain.applicability import (
    assess_policy_scope,
    evaluate_policy_selector,
)
from andromeda.modules.policy.domain.approval import (
    create_approval_event,
    create_pending_submission_event,
)
from andromeda.modules.policy.domain.precedence import (
    ScopeSpecificity,
    resolve_policy_precedence,
    scope_specificity,
)
from andromeda.modules.policy.services.applicability import PolicyApplicabilityService
from andromeda.modules.policy.services.applicability_resolver import (
    EffectiveRuleCandidateResolver,
)
from andromeda.modules.policy.services.effective_rule_resolver import (
    EffectivePolicyResolver,
)
from andromeda.modules.policy.services.ports import PolicyClock

CAPTURED_AT = datetime(2027, 12, 15, tzinfo=UTC)
RECORDED_AT = datetime(2027, 12, 16, tzinfo=UTC)
SOURCE_HASH = "c" * 64
RULE_ID = "policy-rule:bmstu-fourth-exam"


def _revision() -> PolicyRuleRevision:
    fields = PolicyRuleRevisionFields(
        rule_id=RULE_ID,
        revision=1,
        family_id="policy-family:fourth-exam-benefit",
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        selector=PolicySelectorAst(
            nodes=(
                PolicySelectorNode(
                    node_id="root",
                    kind=PolicySelectorNodeKind.ALL,
                ),
                PolicySelectorNode(
                    node_id="university",
                    parent_id="root",
                    kind=PolicySelectorNodeKind.EQUALS,
                    field=PolicyContextField.UNIVERSITY_ID,
                    value="university:bmstu",
                ),
                PolicySelectorNode(
                    node_id="admission-year",
                    parent_id="root",
                    kind=PolicySelectorNodeKind.EQUALS,
                    field=PolicyContextField.ADMISSION_YEAR,
                    value=2028,
                ),
            )
        ),
        scope=PolicyScope(level=PolicyScopeLevel.UNIVERSITY, scope_id="university:bmstu"),
        domain_rule=DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            canonical_rule_id="admission-benefit:fourth-exam",
            owner_revision=3,
        ),
        lifecycle=PolicyRevisionLifecycle.FUTURE_EFFECTIVE,
        temporal=PolicyTemporalRevision(
            clock=BitemporalRevision(
                revision=1,
                valid_time=TemporalInterval(start=datetime(2027, 1, 1, tzinfo=UTC)),
                recorded_at=RECORDED_AT,
            ),
            source_milestones=SourceMilestones(
                captured_at=CAPTURED_AT,
                effective_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
            ),
        ),
        source_claims=(ClaimRevisionRef(claim_id="claim:" + "a" * 64, revision=1),),
        evidence=(
            EvidenceRef(
                source_id="source:ministry-admission",
                source_observation_id="source-observation:" + "b" * 32,
                snapshot_sha256=SOURCE_HASH,
                source_url="https://official.example/policy.pdf",
                locator=EvidenceLocator(page=4),
            ),
        ),
    )
    return PolicyRuleRevision(
        **fields.model_dump(mode="python"),
        content_hash=policy_rule_content_hash(fields),
    )


def _matching_context() -> PolicyApplicabilityContext:
    return PolicyApplicabilityContext(
        values=(
            PolicyContextValue(
                field=PolicyContextField.UNIVERSITY_ID,
                availability=PolicyContextAvailability.PRESENT,
                value="university:bmstu",
            ),
            PolicyContextValue(
                field=PolicyContextField.ADMISSION_YEAR,
                availability=PolicyContextAvailability.PRESENT,
                value=2028,
            ),
        )
    )


class _ApprovedRevisionReader:
    def __init__(
        self,
        revision: PolicyRuleRevision | tuple[PolicyRuleRevision, ...] | None,
        *,
        records_override: tuple[ApprovedPolicyRevision, ...] | None = None,
    ) -> None:
        self.revisions = (
            ()
            if revision is None
            else revision
            if isinstance(revision, tuple)
            else (revision,)
        )
        self.records_override = records_override

    def get_approved_revision(
        self,
        rule_id: str,
        revision: int,
        *,
        as_known_at: datetime | None = None,
    ) -> PolicyRuleRevision | None:
        if as_known_at is not None and as_known_at < RECORDED_AT + timedelta(seconds=5):
            return None
        return next(
            (
                item
                for item in self.revisions
                if (item.rule_id, item.revision) == (rule_id, revision)
            ),
            None,
        )

    def list_approved_revisions(self, *, as_known_at: datetime) -> tuple[PolicyRuleRevision, ...]:
        if as_known_at < RECORDED_AT + timedelta(seconds=5):
            return ()
        return self.revisions

    def list_approved_revision_records(
        self, *, as_known_at: datetime
    ) -> tuple[ApprovedPolicyRevision, ...]:
        if as_known_at < RECORDED_AT + timedelta(seconds=5):
            return ()
        if self.records_override is not None:
            return self.records_override
        records = []
        for revision in self.revisions:
            event = create_approval_event(
                rule_id=revision.rule_id,
                revision=revision.revision,
                revision_hash=revision.content_hash,
                sequence=2,
                kind=PolicyApprovalEventKind.APPROVED,
                actor_account_id="account:" + "e" * 32,
                reason="Exact revision reviewed.",
                recorded_at=revision.temporal.clock.recorded_at + timedelta(seconds=10),
                preview_fingerprint="d" * 64,
            )
            records.append(
                ApprovedPolicyRevision(revision=revision, approval_event=event)
            )
        return tuple(records)


class _DomainReader:
    owner_module = PolicyDomainOwner.ADMISSION_BENEFITS

    def __init__(self, status: PolicyDomainLookupStatus = PolicyDomainLookupStatus.AVAILABLE) -> None:
        self.status = status
        self.calls: list[DomainRuleRef] = []

    def lookup_rule(self, reference: DomainRuleRef) -> PolicyDomainRuleLookup:
        self.calls.append(reference)
        return PolicyDomainRuleLookup(
            requested_reference=reference,
            resolved_reference=reference if self.status is PolicyDomainLookupStatus.AVAILABLE else None,
            status=self.status,
        )


class _CycleReader:
    def __init__(self, cycles: tuple[AdmissionCycle, ...]) -> None:
        self.cycles = cycles

    def resolve_for_admission(
        self,
        university_id: str,
        admission_year: int,
        *,
        as_known_at: datetime | None = None,
    ) -> AdmissionCycleResolution:
        cycle = next(
            (
                item
                for item in self.cycles
                if item.university_id == university_id
                and item.admission_year == admission_year
                and (as_known_at is None or item.recorded_at <= as_known_at)
            ),
            None,
        )
        if cycle is None:
            return AdmissionCycleResolution(
                status=AdmissionCycleResolutionStatus.BLOCKED_BY_MISSING_DATA,
                reason="No source-backed cycle is available at this knowledge time.",
            )
        return AdmissionCycleResolution(
            status=AdmissionCycleResolutionStatus.RESOLVED,
            cycle=cycle,
        )


class _FixedPolicyClock(PolicyClock):
    def now(self) -> datetime:
        return RECORDED_AT + timedelta(seconds=10)


def _cycle(admission_year: int) -> AdmissionCycle:
    return AdmissionCycle(
        cycle_id=f"admission-cycle:bmstu:{admission_year}",
        revision=1,
        university_id="university:bmstu",
        admission_year=admission_year,
        academic_year=f"{admission_year}/{admission_year + 1}",
        application_period=InclusiveDateWindow(
            start_date=date(admission_year, 6, 1),
            end_date=date(admission_year, 6, 30),
        ),
        enrollment_period=InclusiveDateWindow(
            start_date=date(admission_year, 9, 1),
            end_date=date(admission_year, 9, 10),
        ),
        state=AdmissionCycleState.PUBLISHED,
        evidence=(
            EvidenceRef(
                source_id="source:ministry-admission",
                source_observation_id="source-observation:" + "b" * 32,
                snapshot_sha256=SOURCE_HASH,
                source_url="https://official.example/admission/cycle.pdf",
                locator=EvidenceLocator(page=1),
            ),
        ),
        approved_by_account_id="account:" + "e" * 32,
        approved_at=RECORDED_AT + timedelta(seconds=1),
        approval_reason="Cycle dates were checked against the official admission rules.",
        recorded_at=RECORDED_AT + timedelta(seconds=2),
    )


def test_selector_uses_three_valued_logic_and_never_turns_unknown_into_false() -> None:
    revision = _revision()
    unknown_context = PolicyApplicabilityContext(
        values=(
            PolicyContextValue(
                field=PolicyContextField.UNIVERSITY_ID,
                availability=PolicyContextAvailability.PRESENT,
                value="university:bmstu",
            ),
        )
    )
    unknown_trace = evaluate_policy_selector(revision.selector, unknown_context)
    assert next(item for item in unknown_trace if item.node_id == "root").state is (
        SelectorNodeState.INDETERMINATE
    )
    assert next(item for item in unknown_trace if item.node_id == "admission-year").reason is (
        SelectorNodeReason.FIELD_UNKNOWN
    )

    mismatch_context = PolicyApplicabilityContext(
        values=(
            PolicyContextValue(
                field=PolicyContextField.UNIVERSITY_ID,
                availability=PolicyContextAvailability.PRESENT,
                value="university:other",
            ),
        )
    )
    mismatch_trace = evaluate_policy_selector(revision.selector, mismatch_context)
    assert next(item for item in mismatch_trace if item.node_id == "root").state is (
        SelectorNodeState.NO_MATCH
    )


def test_source_backed_cycle_date_is_a_typed_canonical_selector_value() -> None:
    selector = PolicySelectorAst(
        nodes=(
            PolicySelectorNode(
                node_id="application-open",
                kind=PolicySelectorNodeKind.EQUALS,
                field=PolicyContextField.APPLICATION_START_DATE,
                value="2028-06-01",
            ),
        )
    )
    context = PolicyApplicabilityContext(
        values=(
            PolicyContextValue(
                field=PolicyContextField.APPLICATION_START_DATE,
                availability=PolicyContextAvailability.PRESENT,
                origin=PolicyContextOrigin.SOURCE_BACKED_CYCLE,
                value="2028-06-01",
            ),
        )
    )
    assert evaluate_policy_selector(selector, context)[0].state is SelectorNodeState.MATCH

    invalid_date = PolicyApplicabilityContext(
        values=(
            PolicyContextValue(
                field=PolicyContextField.APPLICATION_START_DATE,
                availability=PolicyContextAvailability.PRESENT,
                origin=PolicyContextOrigin.SOURCE_BACKED_CYCLE,
                value="2028-6-1",
            ),
        )
    )
    with pytest.raises(ValueError, match="canonical YYYY-MM-DD"):
        evaluate_policy_selector(selector, invalid_date)


def test_approved_selector_dispatches_only_exact_owner_revision() -> None:
    revision = _revision()
    owner = _DomainReader()
    service = PolicyApplicabilityService(
        approved_revisions=_ApprovedRevisionReader(revision),
        domain_readers=(owner,),
    )

    result = service.assess_approved_revision(
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
        context=_matching_context(),
    )

    assert result.status is PolicyApplicabilityStatus.SELECTOR_MATCHED
    assert result.reason is PolicyApplicabilityReason.SELECTOR_MATCHED
    assert result.selection is not None
    assert result.selection.domain_rule == revision.domain_rule
    assert result.selection.revision_hash == revision.content_hash
    assert owner.calls == [revision.domain_rule]


@pytest.mark.parametrize(
    ("reader_revision", "requested_hash", "expected_reason"),
    [
        (None, SOURCE_HASH, PolicyApplicabilityReason.REVISION_NOT_APPROVED),
        (_revision(), "d" * 64, PolicyApplicabilityReason.REVISION_HASH_MISMATCH),
    ],
)
def test_pending_or_stale_policy_revision_never_reaches_owner_dispatch(
    reader_revision: PolicyRuleRevision | None,
    requested_hash: str,
    expected_reason: PolicyApplicabilityReason,
) -> None:
    owner = _DomainReader()
    service = PolicyApplicabilityService(
        approved_revisions=_ApprovedRevisionReader(reader_revision),
        domain_readers=(owner,),
    )
    result = service.assess_approved_revision(
        rule_id=RULE_ID,
        revision=1,
        revision_hash=requested_hash,
        context=_matching_context(),
    )
    assert result.status is PolicyApplicabilityStatus.UNAPPROVED
    assert result.reason is expected_reason
    assert result.selection is None
    assert not owner.calls


def test_missing_context_and_missing_owner_revision_fail_closed() -> None:
    revision = _revision()
    owner = _DomainReader(PolicyDomainLookupStatus.NOT_FOUND)
    service = PolicyApplicabilityService(
        approved_revisions=_ApprovedRevisionReader(revision),
        domain_readers=(owner,),
    )
    unknown = service.assess_approved_revision(
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
        context=PolicyApplicabilityContext(),
    )
    assert unknown.status is PolicyApplicabilityStatus.INDETERMINATE
    assert unknown.selection is None
    assert not owner.calls

    missing = service.assess_approved_revision(
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
        context=_matching_context(),
    )
    assert missing.status is PolicyApplicabilityStatus.UNSUPPORTED
    assert missing.reason is PolicyApplicabilityReason.OWNER_RULE_NOT_FOUND
    assert missing.domain_lookup is PolicyDomainLookupStatus.NOT_FOUND
    assert missing.selection is None


def _candidate_resolver(cycles: tuple[AdmissionCycle, ...]) -> EffectiveRuleCandidateResolver:
    return EffectiveRuleCandidateResolver(
        policies=_ApprovedRevisionReader(_revision()),
        admission_cycles=_CycleReader(cycles),
        domain_readers=(_DomainReader(),),
        clock=_FixedPolicyClock(),
    )


def test_2027_and_2028_cohorts_get_different_results_for_one_future_rule() -> None:
    resolver = _candidate_resolver((_cycle(2027), _cycle(2028)))
    as_known_at = RECORDED_AT + timedelta(seconds=10)
    earlier = resolver.resolve(
        PolicyResolutionRequest(
            university_id="university:bmstu",
            admission_year=2027,
            valid_as_of=datetime(2027, 6, 15, tzinfo=UTC),
            as_known_at=as_known_at,
        )
    )
    assert earlier.status is PolicyResolutionStatus.NO_MATCH
    assert earlier.candidates == ()
    assert len(earlier.considered) == 1
    assert earlier.considered[0].filter_state is PolicyRuleFilterState.FUTURE
    assert earlier.considered[0].reason is PolicyRuleFilterReason.FUTURE_EFFECTIVE
    assert earlier.cycle_id == "admission-cycle:bmstu:2027"

    later_request = PolicyResolutionRequest(
        university_id="university:bmstu",
        admission_year=2028,
        valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
        as_known_at=as_known_at,
    )
    later = resolver.resolve(later_request)
    repeated = resolver.resolve(later_request)
    assert later.status is PolicyResolutionStatus.CANDIDATES_FOUND
    assert len(later.candidates) == 1
    assert later.candidates[0].rule_id == RULE_ID
    assert later.cycle_id == "admission-cycle:bmstu:2028"
    assert later.cycle_evidence == _cycle(2028).evidence
    assert later.context_fingerprint == repeated.context_fingerprint
    assert later.trace_id == repeated.trace_id


def test_resolution_blocks_missing_cycle_and_missing_valid_time() -> None:
    resolver = _candidate_resolver(())
    no_cycle = resolver.resolve(
        PolicyResolutionRequest(
            university_id="university:bmstu",
            admission_year=2028,
            valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
            as_known_at=RECORDED_AT + timedelta(seconds=10),
        )
    )
    assert no_cycle.status is PolicyResolutionStatus.BLOCKED_BY_MISSING_DATA
    assert no_cycle.candidates == ()
    assert no_cycle.blockers

    no_valid_time = _candidate_resolver((_cycle(2028),)).resolve(
        PolicyResolutionRequest(
            university_id="university:bmstu",
            admission_year=2028,
            as_known_at=RECORDED_AT + timedelta(seconds=10),
        )
    )
    assert no_valid_time.status is PolicyResolutionStatus.BLOCKED_BY_MISSING_DATA
    assert PolicyRuleFilterReason.VALID_AS_OF_MISSING in tuple(
        item.reason for item in no_valid_time.considered
    )


def test_empty_approved_rule_scan_is_indeterminate_not_a_negative_answer() -> None:
    resolver = EffectiveRuleCandidateResolver(
        policies=_ApprovedRevisionReader(None),
        admission_cycles=_CycleReader((_cycle(2028),)),
        domain_readers=(),
        clock=_FixedPolicyClock(),
    )
    trace = resolver.resolve(
        PolicyResolutionRequest(
            university_id="university:bmstu",
            admission_year=2028,
            valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
            as_known_at=RECORDED_AT + timedelta(seconds=10),
        )
    )
    assert trace.status is PolicyResolutionStatus.INDETERMINATE
    assert trace.considered == ()
    assert trace.candidates == ()


def _variant(
    base: PolicyRuleRevision,
    *,
    rule_id: str,
    scope: PolicyScope,
    authority: PolicyAuthorityLevel,
    family_id: str = "policy-family:fourth-exam-benefit",
    relations: tuple[PolicyRuleRelation, ...] = (),
) -> PolicyRuleRevision:
    fields = PolicyRuleRevisionFields(
        rule_id=rule_id,
        revision=1,
        family_id=family_id,
        authority=authority,
        selector=base.selector,
        scope=scope,
        domain_rule=base.domain_rule,
        lifecycle=base.lifecycle,
        temporal=base.temporal,
        source_claims=base.source_claims,
        evidence=base.evidence,
        relations=relations,
    )
    return PolicyRuleRevision(
        **fields.model_dump(mode="python"),
        content_hash=policy_rule_content_hash(fields),
    )


def test_policy_scope_is_typed_unknown_or_mismatch_not_assumed() -> None:
    scope = PolicyScope(level=PolicyScopeLevel.PROGRAM, scope_id="program:bmstu:example")
    unknown = assess_policy_scope(scope, _matching_context())
    assert unknown.state is PolicyScopeMatchState.INDETERMINATE

    program_context = PolicyApplicabilityContext(
        values=(
            *_matching_context().values,
            PolicyContextValue(
                field=PolicyContextField.PROGRAM_ID,
                availability=PolicyContextAvailability.PRESENT,
                value="program:bmstu:other",
            ),
        )
    )
    mismatched = assess_policy_scope(scope, program_context)
    assert mismatched.state is PolicyScopeMatchState.NO_MATCH


def test_precedence_requires_an_explicit_authorized_edge_for_lower_authority_exception() -> None:
    base = _revision()
    federal = _variant(
        base,
        rule_id="policy-rule:bmstu-federal-baseline",
        scope=PolicyScope(level=PolicyScopeLevel.FEDERAL),
        authority=PolicyAuthorityLevel.FEDERAL_NORMATIVE,
    )
    exception = _variant(
        base,
        rule_id="policy-rule:bmstu-program-exception",
        scope=PolicyScope(level=PolicyScopeLevel.PROGRAM, scope_id="program:bmstu:example"),
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        relations=(
            PolicyRuleRelation(
                kind=PolicyRuleRelationKind.AUTHORIZED_EXCEPTION_TO,
                target_rule_id=federal.rule_id,
                target_revision=federal.revision,
                target_hash=federal.content_hash,
                source_claim=base.source_claims[0],
                evidence=base.evidence[0],
            ),
        ),
    )

    resolved = resolve_policy_precedence((federal, exception))
    assert resolved.status == "resolved"
    assert tuple(item.rule_id for item in resolved.effective_rules) == (exception.rule_id,)
    assert resolved.decisions[0].outcome is PolicyPrecedenceOutcome.RIGHT_PREVAILS
    assert resolved.decisions[0].reason is PolicyPrecedenceReason.AUTHORIZED_EXCEPTION
    assert resolved.decisions[0].relation_kind is PolicyRuleRelationKind.AUTHORIZED_EXCEPTION_TO
    assert resolved.decisions[0].evidence == (base.evidence[0],)


def test_precedence_requires_exact_relation_for_supersession_and_fails_closed_on_bad_edge() -> None:
    base = _revision()
    old = _variant(
        base,
        rule_id="policy-rule:bmstu-old-rule",
        scope=base.scope,
        authority=PolicyAuthorityLevel.REGULATOR_NORMATIVE,
    )
    new = _variant(
        base,
        rule_id="policy-rule:bmstu-new-rule",
        scope=base.scope,
        authority=PolicyAuthorityLevel.REGULATOR_NORMATIVE,
        relations=(
            PolicyRuleRelation(
                kind=PolicyRuleRelationKind.SUPERSEDES,
                target_rule_id=old.rule_id,
                target_revision=old.revision,
                target_hash=old.content_hash,
                source_claim=base.source_claims[0],
                evidence=base.evidence[0],
            ),
        ),
    )
    result = resolve_policy_precedence((old, new))
    assert result.status == "resolved"
    assert tuple(item.rule_id for item in result.effective_rules) == (new.rule_id,)
    assert result.decisions[0].relation_kind is PolicyRuleRelationKind.SUPERSEDES
    assert result.decisions[0].reason is PolicyPrecedenceReason.EXACT_RELATION

    unauthorized = _variant(
        base,
        rule_id="policy-rule:bmstu-unapproved-override",
        scope=PolicyScope(level=PolicyScopeLevel.PROGRAM, scope_id="program:bmstu:example"),
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        relations=(
            PolicyRuleRelation(
                kind=PolicyRuleRelationKind.OVERRIDES,
                target_rule_id=old.rule_id,
                target_revision=old.revision,
                target_hash=old.content_hash,
                source_claim=base.source_claims[0],
                evidence=base.evidence[0],
            ),
        ),
    )
    rejected_edge = resolve_policy_precedence((old, unauthorized))
    assert rejected_edge.status == "conflict"
    assert rejected_edge.decisions[0].reason is PolicyPrecedenceReason.CROSSING_AUTHORITY_AND_SCOPE


def test_precedence_conflicts_on_equal_authority_and_crossing_scope_authority() -> None:
    base = _revision()
    university = _variant(
        base,
        rule_id="policy-rule:bmstu-university-a",
        scope=base.scope,
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
    )
    same_level = _variant(
        base,
        rule_id="policy-rule:bmstu-university-b",
        scope=base.scope,
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
    )
    equal_scope = resolve_policy_precedence((university, same_level))
    assert equal_scope.status == "conflict"
    assert {item.rule_id for item in equal_scope.conflicting_rules} == {
        university.rule_id,
        same_level.rule_id,
    }
    assert equal_scope.decisions[0].reason is PolicyPrecedenceReason.EQUAL_PRECEDENCE

    federal = _variant(
        base,
        rule_id="policy-rule:bmstu-federal",
        scope=PolicyScope(level=PolicyScopeLevel.FEDERAL),
        authority=PolicyAuthorityLevel.FEDERAL_NORMATIVE,
    )
    program = _variant(
        base,
        rule_id="policy-rule:bmstu-program",
        scope=PolicyScope(level=PolicyScopeLevel.PROGRAM, scope_id="program:bmstu:example"),
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
    )
    crossing = resolve_policy_precedence((federal, program))
    assert crossing.status == "conflict"
    assert crossing.decisions[0].reason is PolicyPrecedenceReason.CROSSING_AUTHORITY_AND_SCOPE


def test_precedence_uses_registered_specificity_and_authority_only_on_comparable_scope() -> None:
    assert scope_specificity(
        PolicyScope(level=PolicyScopeLevel.UNIVERSITY, scope_id="university:bmstu"),
        PolicyScope(level=PolicyScopeLevel.PROGRAM, scope_id="program:bmstu:example"),
    ) is ScopeSpecificity.RIGHT_NARROWER
    assert scope_specificity(
        PolicyScope(level=PolicyScopeLevel.FACULTY, scope_id="faculty:bmstu:ict"),
        PolicyScope(level=PolicyScopeLevel.DIRECTION, scope_id="direction:bmstu:cs"),
    ) is ScopeSpecificity.INCOMPARABLE

    base = _revision()
    broad = _variant(
        base,
        rule_id="policy-rule:bmstu-broad",
        scope=PolicyScope(level=PolicyScopeLevel.UNIVERSITY, scope_id="university:bmstu"),
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
    )
    narrow = _variant(
        base,
        rule_id="policy-rule:bmstu-narrow",
        scope=PolicyScope(level=PolicyScopeLevel.PROGRAM, scope_id="program:bmstu:example"),
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
    )
    result = resolve_policy_precedence((broad, narrow))
    assert result.status == "resolved"
    assert tuple(item.rule_id for item in result.effective_rules) == (narrow.rule_id,)
    assert result.decisions[0].reason is PolicyPrecedenceReason.SPECIFICITY

    higher_authority = _variant(
        base,
        rule_id="policy-rule:bmstu-regulator",
        scope=base.scope,
        authority=PolicyAuthorityLevel.REGULATOR_NORMATIVE,
    )
    authority_result = resolve_policy_precedence((broad, higher_authority))
    assert authority_result.status == "resolved"
    assert tuple(item.rule_id for item in authority_result.effective_rules) == (
        higher_authority.rule_id,
    )
    assert authority_result.decisions[0].reason is PolicyPrecedenceReason.AUTHORITY

    unresolved = _variant(
        base,
        rule_id="policy-rule:bmstu-unresolved-authority",
        scope=base.scope,
        authority=PolicyAuthorityLevel.UNRESOLVED,
    )
    unresolved_result = resolve_policy_precedence((unresolved,))
    assert unresolved_result.status == "indeterminate"
    assert unresolved_result.effective_rules == ()


def test_effective_policy_resolver_emits_exact_effective_rule_and_content_addressed_trace() -> None:
    resolver = EffectivePolicyResolver(
        policies=_ApprovedRevisionReader(_revision()),
        admission_cycles=_CycleReader((_cycle(2028),)),
        domain_readers=(_DomainReader(),),
        clock=_FixedPolicyClock(),
    )
    request = PolicyResolutionRequest(
        university_id="university:bmstu",
        admission_year=2028,
        valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
        as_known_at=RECORDED_AT + timedelta(seconds=10),
    )
    trace = resolver.resolve(request)
    repeated = resolver.resolve(request)
    assert trace.status is PolicyResolutionStatus.RESOLVED
    assert tuple(item.rule_id for item in trace.effective_rules) == (RULE_ID,)
    assert trace.trace_version == "policy-resolution-trace.v3"
    assert trace.considered[0].approval_event is not None
    assert trace.considered[0].approval_event.revision_hash == trace.considered[0].revision_hash
    assert trace.trace_id == repeated.trace_id
    assert trace.precedence_decisions == ()


def test_resolution_trace_references_the_exact_immutable_approval_event() -> None:
    reader = _ApprovedRevisionReader(_revision())
    approved = reader.list_approved_revision_records(
        as_known_at=RECORDED_AT + timedelta(seconds=10)
    )[0]
    trace = EffectivePolicyResolver(
        policies=reader,
        admission_cycles=_CycleReader((_cycle(2028),)),
        domain_readers=(_DomainReader(),),
        clock=_FixedPolicyClock(),
    ).resolve(
        PolicyResolutionRequest(
            university_id="university:bmstu",
            admission_year=2028,
            valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
            as_known_at=RECORDED_AT + timedelta(seconds=10),
        )
    )

    reference = trace.considered[0].approval_event
    assert reference is not None
    assert reference.event_id == approved.approval_event.event_id
    assert reference.revision == approved.revision.revision
    assert reference.revision_hash == approved.revision.content_hash
    assert reference.sequence == approved.approval_event.sequence


def test_new_policy_revision_cannot_inherit_approval_from_previous_revision() -> None:
    previous = _revision()
    old_record = _ApprovedRevisionReader(previous).list_approved_revision_records(
        as_known_at=RECORDED_AT + timedelta(seconds=10)
    )[0]
    fields = PolicyRuleRevisionFields(
        **{
            **previous.model_dump(exclude={"content_hash"}, mode="python"),
            "revision": 2,
            "temporal": previous.temporal.model_copy(
                update={
                    "clock": previous.temporal.clock.model_copy(
                        update={
                            "revision": 2,
                            "recorded_at": RECORDED_AT + timedelta(days=1),
                        }
                    )
                }
            ),
        }
    )
    next_revision = PolicyRuleRevision(
        **fields.model_dump(mode="python"),
        content_hash=policy_rule_content_hash(fields),
    )

    with pytest.raises(ValueError, match="exact policy revision"):
        ApprovedPolicyRevision(
            revision=next_revision,
            approval_event=old_record.approval_event,
        )


@pytest.mark.parametrize(
    "event_kind",
    (PolicyApprovalEventKind.PENDING_SUBMITTED, PolicyApprovalEventKind.REJECTED),
)
def test_pending_or_rejected_revision_never_enters_effective_selection(
    event_kind: PolicyApprovalEventKind,
) -> None:
    revision = _revision()
    if event_kind is PolicyApprovalEventKind.PENDING_SUBMITTED:
        event = create_pending_submission_event(
            revision,
            actor_account_id="account:" + "e" * 32,
            reason="Revision remains pending.",
            recorded_at=RECORDED_AT + timedelta(seconds=10),
        )
    else:
        event = create_approval_event(
            rule_id=revision.rule_id,
            revision=revision.revision,
            revision_hash=revision.content_hash,
            sequence=2,
            kind=event_kind,
            actor_account_id="account:" + "e" * 32,
            reason="Revision has no current approval.",
            recorded_at=RECORDED_AT + timedelta(seconds=10),
        )
    invalid_record = ApprovedPolicyRevision.model_construct(
        revision=revision,
        approval_event=event,
    )
    reader = _ApprovedRevisionReader(
        revision,
        records_override=(invalid_record,),
    )
    trace = EffectivePolicyResolver(
        policies=reader,
        admission_cycles=_CycleReader((_cycle(2028),)),
        domain_readers=(_DomainReader(),),
        clock=_FixedPolicyClock(),
    ).resolve(
        PolicyResolutionRequest(
            university_id="university:bmstu",
            admission_year=2028,
            valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
            as_known_at=RECORDED_AT + timedelta(seconds=10),
        )
    )

    assert trace.status is PolicyResolutionStatus.INDETERMINATE
    assert trace.effective_rules == ()
    assert PolicyResolutionBlocker.APPROVAL_PROVENANCE_INVALID in trace.blockers


@pytest.mark.parametrize("mismatch", ("revision", "revision_hash"))
def test_approval_event_binding_mismatch_fails_closed(mismatch: str) -> None:
    revision = _revision()
    record = _ApprovedRevisionReader(revision).list_approved_revision_records(
        as_known_at=RECORDED_AT + timedelta(seconds=10)
    )[0]
    bad_event = record.approval_event.model_copy(
        update={
            mismatch: 2 if mismatch == "revision" else "f" * 64,
        }
    )
    invalid_record = ApprovedPolicyRevision.model_construct(
        revision=revision,
        approval_event=bad_event,
    )
    trace = EffectivePolicyResolver(
        policies=_ApprovedRevisionReader(
            revision,
            records_override=(invalid_record,),
        ),
        admission_cycles=_CycleReader((_cycle(2028),)),
        domain_readers=(_DomainReader(),),
        clock=_FixedPolicyClock(),
    ).resolve(
        PolicyResolutionRequest(
            university_id="university:bmstu",
            admission_year=2028,
            valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
            as_known_at=RECORDED_AT + timedelta(seconds=10),
        )
    )

    assert trace.status is PolicyResolutionStatus.INDETERMINATE
    assert trace.effective_rules == ()
    assert PolicyResolutionBlocker.APPROVAL_PROVENANCE_INVALID in trace.blockers


def test_effective_policy_resolver_blocks_equal_precedence_candidates_with_trace() -> None:
    first = _revision()
    second = _variant(
        first,
        rule_id="policy-rule:bmstu-fourth-exam-copy",
        scope=first.scope,
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
    )
    resolver = EffectivePolicyResolver(
        policies=_ApprovedRevisionReader((first, second)),
        admission_cycles=_CycleReader((_cycle(2028),)),
        domain_readers=(_DomainReader(),),
        clock=_FixedPolicyClock(),
    )
    request = PolicyResolutionRequest(
        university_id="university:bmstu",
        admission_year=2028,
        valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
        as_known_at=RECORDED_AT + timedelta(seconds=10),
    )

    trace = resolver.resolve(request)

    assert trace.status is PolicyResolutionStatus.CONFLICT
    assert trace.effective_rules == ()
    assert {item.rule_id for item in trace.conflicting_rules} == {first.rule_id, second.rule_id}
    assert trace.precedence_decisions[0].reason is PolicyPrecedenceReason.EQUAL_PRECEDENCE
    assert trace.trace_id == resolver.resolve(request).trace_id
    reordered_reader = EffectivePolicyResolver(
        policies=_ApprovedRevisionReader((second, first)),
        admission_cycles=_CycleReader((_cycle(2028),)),
        domain_readers=(_DomainReader(),),
        clock=_FixedPolicyClock(),
    )
    assert reordered_reader.resolve(request).trace_id == trace.trace_id


def test_effective_policy_resolver_fails_closed_when_precedence_trace_limit_is_reached() -> None:
    base = _revision()
    candidates = tuple(
        _variant(
            base,
            rule_id=f"policy-rule:bmstu-fourth-exam-{index:03}",
            scope=base.scope,
            authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        )
        for index in range(101)
    )
    resolver = EffectivePolicyResolver(
        policies=_ApprovedRevisionReader(candidates),
        admission_cycles=_CycleReader((_cycle(2028),)),
        domain_readers=(_DomainReader(),),
        clock=_FixedPolicyClock(),
    )
    request = PolicyResolutionRequest(
        university_id="university:bmstu",
        admission_year=2028,
        valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
        as_known_at=RECORDED_AT + timedelta(seconds=10),
    )

    trace = resolver.resolve(request)

    assert trace.status is PolicyResolutionStatus.INDETERMINATE
    assert trace.effective_rules == ()
    assert trace.blockers == (PolicyResolutionBlocker.PRECEDENCE_DECISION_LIMIT,)
    assert len(trace.precedence_decisions) == 5000
    assert trace.trace_id == resolver.resolve(request).trace_id


def test_direction_exception_requires_exact_source_backed_federal_edge() -> None:
    base = _revision()
    federal = _variant(
        base,
        rule_id="policy-rule:bmstu-federal-exam-count",
        scope=PolicyScope(level=PolicyScopeLevel.FEDERAL),
        authority=PolicyAuthorityLevel.FEDERAL_NORMATIVE,
    )
    direction = _variant(
        base,
        rule_id="policy-rule:bmstu-direction-exam-count",
        scope=PolicyScope(
            level=PolicyScopeLevel.DIRECTION,
            scope_id="direction:bmstu:01.03.02",
        ),
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        relations=(
            PolicyRuleRelation(
                kind=PolicyRuleRelationKind.AUTHORIZED_EXCEPTION_TO,
                target_rule_id=federal.rule_id,
                target_revision=federal.revision,
                target_hash=federal.content_hash,
                source_claim=base.source_claims[0],
                evidence=base.evidence[0],
            ),
        ),
    )

    result = resolve_policy_precedence((federal, direction))

    assert result.status == "resolved"
    assert tuple(item.rule_id for item in result.effective_rules) == (direction.rule_id,)
    assert result.decisions[0].reason is PolicyPrecedenceReason.AUTHORIZED_EXCEPTION
    assert result.decisions[0].relation_kind is PolicyRuleRelationKind.AUTHORIZED_EXCEPTION_TO
    assert result.decisions[0].evidence == (base.evidence[0],)
