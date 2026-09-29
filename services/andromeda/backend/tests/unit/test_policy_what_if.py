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
    EvidenceRef,
    SourceMilestones,
    TemporalInterval,
)
from andromeda.modules.policy.contracts.applicability import (
    PolicyDomainLookupStatus,
    PolicyDomainRuleLookup,
)
from andromeda.modules.policy.contracts.approval import (
    ApprovedPolicyRevision,
    PolicyApprovalCapability,
    PolicyApprovalCommand,
    PolicyApprovalEvent,
    PolicyApprovalEventKind,
    PolicyApprovalState,
)
from andromeda.modules.policy.contracts.impact import (
    DomainImpactStatus,
    DomainRuleImpactObservation,
    ImpactActionability,
)
from andromeda.modules.policy.contracts.resolution import (
    PolicyResolutionMode,
    PolicyResolutionRequest,
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
from andromeda.modules.policy.contracts.semantic_diff import (
    PolicyDiffChangeKind,
    PolicyDiffEntry,
)
from andromeda.modules.policy.contracts.temporal import PolicyTemporalRevision
from andromeda.modules.policy.domain.approval import (
    create_approval_event,
    create_pending_submission_event,
)
from andromeda.modules.policy.services.approval import PolicyApprovalCommandService
from andromeda.modules.policy.services.effective_rule_resolver import (
    EffectivePolicyResolver,
)
from andromeda.modules.policy.services.ports import PolicyClock
from andromeda.modules.policy.services.sandbox_evaluator import (
    PolicyHypotheticalSandbox,
)
from andromeda.shared.contracts.errors import ConflictError, ValidationError

NOW = datetime(2028, 6, 15, tzinfo=UTC)
SOURCE_HASH = "c" * 64
EVIDENCE = EvidenceRef(
    source_id="source:official-policy",
    source_observation_id="source-observation:" + "d" * 32,
    snapshot_sha256=SOURCE_HASH,
    source_url="https://official.example/admission-rules.pdf",
)
CURRENT_RULE_ID = "policy-rule:benefit-current"
CANDIDATE_RULE_ID = "policy-rule:benefit-candidate"
FAMILY_ID = "policy-family:admission-benefit"
UNIVERSITY_ID = "university:bmstu"


def _revision(
    *,
    rule_id: str,
    owner_revision: int,
    owner_hash: str,
    relation: PolicyRuleRelation | None = None,
) -> PolicyRuleRevision:
    claim = ClaimRevisionRef(
        claim_id="claim:" + ("a" if owner_revision == 1 else "b") * 64,
        revision=1,
    )
    fields = PolicyRuleRevisionFields(
        schema_version="policy-rule.v3",
        rule_id=rule_id,
        revision=1,
        family_id=FAMILY_ID,
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        selector=PolicySelectorAst(
            nodes=(
                PolicySelectorNode(node_id="root", kind=PolicySelectorNodeKind.ALL),
                PolicySelectorNode(
                    node_id="university",
                    parent_id="root",
                    kind=PolicySelectorNodeKind.EQUALS,
                    field=PolicyContextField.UNIVERSITY_ID,
                    value=UNIVERSITY_ID,
                ),
                PolicySelectorNode(
                    node_id="year",
                    parent_id="root",
                    kind=PolicySelectorNodeKind.EQUALS,
                    field=PolicyContextField.ADMISSION_YEAR,
                    value=2028,
                ),
            )
        ),
        scope=PolicyScope(level=PolicyScopeLevel.UNIVERSITY, scope_id=UNIVERSITY_ID),
        domain_rule=DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            canonical_rule_id="admission-benefit:olympiad-benefit",
            owner_revision=owner_revision,
            owner_revision_hash=owner_hash,
        ),
        lifecycle=PolicyRevisionLifecycle.EFFECTIVE,
        temporal=PolicyTemporalRevision(
            clock=BitemporalRevision(
                revision=1,
                valid_time=TemporalInterval(start=datetime(2028, 1, 1, tzinfo=UTC)),
                recorded_at=datetime(2028, 1, 2, tzinfo=UTC),
            ),
            source_milestones=SourceMilestones(
                captured_at=datetime(2028, 1, 1, tzinfo=UTC),
                effective_time=TemporalInterval(start=datetime(2028, 1, 1, tzinfo=UTC)),
            ),
        ),
        source_claims=(claim,),
        evidence=(EVIDENCE,),
        relations=(relation,) if relation is not None else (),
    )
    return PolicyRuleRevision(
        **fields.model_dump(mode="python"),
        content_hash=policy_rule_content_hash(fields),
    )


CURRENT_REVISION = _revision(
    rule_id=CURRENT_RULE_ID,
    owner_revision=1,
    owner_hash="1" * 64,
)
CANDIDATE_REVISION = _revision(
    rule_id=CANDIDATE_RULE_ID,
    owner_revision=2,
    owner_hash="2" * 64,
    relation=PolicyRuleRelation(
        kind=PolicyRuleRelationKind.SUPERSEDES,
        target_rule_id=CURRENT_RULE_ID,
        target_revision=1,
        target_hash=CURRENT_REVISION.content_hash,
        source_claim=ClaimRevisionRef(claim_id="claim:" + "b" * 64, revision=1),
        evidence=EVIDENCE,
    ),
)


class _CycleReader:
    def resolve_for_admission(self, university_id, admission_year, *, as_known_at=None):
        assert university_id == UNIVERSITY_ID
        return AdmissionCycleResolution(
            status=AdmissionCycleResolutionStatus.RESOLVED,
            cycle=AdmissionCycle(
                cycle_id=f"admission-cycle:bmstu:{admission_year}",
                revision=1,
                university_id=UNIVERSITY_ID,
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
                evidence=(EVIDENCE,),
                approved_by_account_id="account:" + "f" * 32,
                approved_at=datetime(2028, 1, 3, tzinfo=UTC),
                approval_reason="Verified against the official schedule.",
                recorded_at=datetime(2028, 1, 3, tzinfo=UTC),
            ),
        )


class _OwnerReader:
    owner_module = PolicyDomainOwner.ADMISSION_BENEFITS

    def lookup_rule(self, reference):
        return PolicyDomainRuleLookup(
            requested_reference=reference,
            status=PolicyDomainLookupStatus.AVAILABLE,
            resolved_reference=reference,
        )


class _OwnerImpactReader:
    owner_module = PolicyDomainOwner.ADMISSION_BENEFITS

    def compare_policy_rules(self, before, after, *, context):
        assert before is not None and after is not None
        return DomainRuleImpactObservation(
            owner_module=self.owner_module,
            before_rule=before,
            after_rule=after,
            status=DomainImpactStatus.EVALUATED,
            actionability=ImpactActionability.UNCERTAIN,
            changes=(
                PolicyDiffEntry(
                    path="domain_owner.admission_benefits.confirmation_threshold",
                    kind=PolicyDiffChangeKind.CHANGED,
                    before="75",
                    after="80",
                    before_evidence=(EVIDENCE,),
                    after_evidence=(EVIDENCE,),
                    reason_code="owner_rule_revision_changed",
                ),
            ),
            evidence=(EVIDENCE,),
        )


class _Clock(PolicyClock):
    def now(self) -> datetime:
        return NOW


class _ReviewReader:
    def __init__(
        self, candidate_state: PolicyApprovalState = PolicyApprovalState.PENDING
    ):
        self.candidate_state = candidate_state
        self.write_calls = 0
        self.appended_events: list[PolicyApprovalEvent] = []
        self.pending_event = create_pending_submission_event(
            CANDIDATE_REVISION,
            actor_account_id="account:" + "e" * 32,
            reason="Candidate extracted from an official revision.",
            recorded_at=datetime(2028, 1, 2, tzinfo=UTC),
        )

    def get_approved_revision(self, rule_id, revision, *, as_known_at=None):
        raise AssertionError("sandbox must consume a bounded approved snapshot")

    def list_approved_revisions(self, *, as_known_at):
        return (CURRENT_REVISION,)

    def list_approved_revision_records(self, *, as_known_at):
        event = create_approval_event(
            rule_id=CURRENT_REVISION.rule_id,
            revision=CURRENT_REVISION.revision,
            revision_hash=CURRENT_REVISION.content_hash,
            sequence=2,
            kind=PolicyApprovalEventKind.APPROVED,
            actor_account_id="account:" + "e" * 32,
            reason="Current policy revision reviewed.",
            recorded_at=datetime(2028, 1, 2, 0, 0, 10, tzinfo=UTC),
            preview_fingerprint="d" * 64,
        )
        return (ApprovedPolicyRevision(revision=CURRENT_REVISION, approval_event=event),)

    def get_revision(self, rule_id, revision):
        if (rule_id, revision) == (CANDIDATE_RULE_ID, 1):
            return CANDIDATE_REVISION
        return None

    def list_approval_events(self, rule_id, revision, *, as_known_at=None):
        if (rule_id, revision) != (CANDIDATE_RULE_ID, 1):
            return ()
        if self.candidate_state is PolicyApprovalState.PENDING:
            return (self.pending_event,)
        return ()

    def append_approval_event(self, event: PolicyApprovalEvent) -> PolicyApprovalEvent:
        self.write_calls += 1
        self.appended_events.append(event)
        return event


class _AllowPolicyApproval:
    def require_capability(self, actor_account_id: str, capability: PolicyApprovalCapability) -> None:
        assert actor_account_id == "account:" + "e" * 32
        assert capability is PolicyApprovalCapability.APPROVE_REVISION


class _ApprovalUnitOfWork:
    def __init__(self) -> None:
        self.rollback_count = 0

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        self.rollback_count += 1


class _ApprovalConflicts:
    def __init__(self, *, open_conflict: bool = False) -> None:
        self.open_conflict = open_conflict
        self.calls: list[tuple[str, int, str]] = []

    def has_open_conflicts(self, rule_id: str, revision: int, revision_hash: str) -> bool:
        self.calls.append((rule_id, revision, revision_hash))
        return self.open_conflict


def _sandbox(reader: _ReviewReader) -> PolicyHypotheticalSandbox:
    return PolicyHypotheticalSandbox(
        revisions=reader,
        admission_cycles=_CycleReader(),
        domain_readers=(_OwnerReader(),),
        domain_impact_readers=(_OwnerImpactReader(),),
        clock=_Clock(),
    )


def test_pending_revision_preview_is_explicitly_hypothetical_and_repeatable() -> None:
    reader = _ReviewReader()
    sandbox = _sandbox(reader)
    request = PolicyResolutionRequest(
        university_id=UNIVERSITY_ID,
        admission_year=2028,
        valid_as_of=NOW,
        as_known_at=NOW,
    )

    first = sandbox.preview(
        request,
        rule_id=CANDIDATE_RULE_ID,
        revision=1,
        revision_hash=CANDIDATE_REVISION.content_hash,
    )
    second = sandbox.preview(
        request,
        rule_id=CANDIDATE_RULE_ID,
        revision=1,
        revision_hash=CANDIDATE_REVISION.content_hash,
    )

    assert first.hypothetical is True
    assert first.approval_state is PolicyApprovalState.PENDING
    assert first.current_trace.mode is PolicyResolutionMode.APPROVED_EFFECTIVE
    assert first.candidate_trace.mode is PolicyResolutionMode.HYPOTHETICAL
    assert tuple(item.rule_id for item in first.current_trace.effective_rules) == (
        CURRENT_RULE_ID,
    )
    assert tuple(item.rule_id for item in first.candidate_trace.effective_rules) == (
        CANDIDATE_RULE_ID,
    )
    assert first.impact.domain_results[0].changes[0].after == "80"
    assert first.current_trace.trace_id == second.current_trace.trace_id
    assert first.candidate_trace.trace_id == second.candidate_trace.trace_id
    assert first.preview_id == second.preview_id
    assert reader.write_calls == 0


def test_policy_approval_service_enforces_preview_impact_and_conflict_gates() -> None:
    request = PolicyResolutionRequest(
        university_id=UNIVERSITY_ID,
        admission_year=2028,
        valid_as_of=NOW,
        as_known_at=NOW,
    )
    reader = _ReviewReader()
    preview = _sandbox(reader).preview(
        request,
        rule_id=CANDIDATE_RULE_ID,
        revision=1,
        revision_hash=CANDIDATE_REVISION.content_hash,
    )
    command = PolicyApprovalCommand(
        rule_id=CANDIDATE_RULE_ID,
        revision=1,
        revision_hash=CANDIDATE_REVISION.content_hash,
        kind=PolicyApprovalEventKind.APPROVED,
        actor_account_id="account:" + "e" * 32,
        reason="Approve after checking exact preview and evidence.",
        recorded_at=NOW + timedelta(seconds=1),
        preview_fingerprint=preview.preview_id.partition(":")[2],
    )
    unit_of_work = _ApprovalUnitOfWork()
    conflicts = _ApprovalConflicts()
    service = PolicyApprovalCommandService(
        repository=reader,  # type: ignore[arg-type]
        authorizer=_AllowPolicyApproval(),  # type: ignore[arg-type]
        unit_of_work=unit_of_work,
        approval_conflicts=conflicts,
    )

    with pytest.raises(ValidationError, match="reviewed preview gate"):
        service.decide(command)
    assert reader.write_calls == 0
    assert unit_of_work.rollback_count == 1

    approval = service.decide(command, review_preview=preview)
    assert approval.kind is PolicyApprovalEventKind.APPROVED
    assert reader.appended_events == [approval]
    assert conflicts.calls == [(CANDIDATE_RULE_ID, 1, CANDIDATE_REVISION.content_hash)]

    blocked_reader = _ReviewReader()
    blocked_unit_of_work = _ApprovalUnitOfWork()
    blocked_service = PolicyApprovalCommandService(
        repository=blocked_reader,  # type: ignore[arg-type]
        authorizer=_AllowPolicyApproval(),  # type: ignore[arg-type]
        unit_of_work=blocked_unit_of_work,
        approval_conflicts=_ApprovalConflicts(open_conflict=True),
    )
    with pytest.raises(ConflictError, match="unresolved conflict"):
        blocked_service.decide(command, review_preview=preview)
    assert blocked_reader.write_calls == 0
    assert blocked_unit_of_work.rollback_count == 1


def test_sandbox_refuses_non_pending_revision_and_does_not_touch_approval_gate() -> (
    None
):
    sandbox = _sandbox(_ReviewReader(candidate_state=PolicyApprovalState.APPROVED))
    with pytest.raises(ConflictError, match="Only an exact pending"):
        sandbox.preview(
            PolicyResolutionRequest(
                university_id=UNIVERSITY_ID,
                admission_year=2028,
                valid_as_of=NOW,
                as_known_at=NOW,
            ),
            rule_id=CANDIDATE_RULE_ID,
            revision=1,
            revision_hash=CANDIDATE_REVISION.content_hash,
        )


def test_2028_candidate_is_not_applied_to_the_2027_admission_cycle() -> None:
    sandbox = _sandbox(_ReviewReader())
    preview = sandbox.preview(
        PolicyResolutionRequest(
            university_id=UNIVERSITY_ID,
            admission_year=2027,
            valid_as_of=NOW,
            as_known_at=NOW,
        ),
        rule_id=CANDIDATE_RULE_ID,
        revision=1,
        revision_hash=CANDIDATE_REVISION.content_hash,
    )

    assert preview.hypothetical is True
    assert preview.current_trace.admission_year == 2027
    assert preview.candidate_trace.admission_year == 2027
    assert preview.candidate_trace.effective_rules == ()
    candidate = next(
        item
        for item in preview.candidate_trace.considered
        if item.rule_id == CANDIDATE_RULE_ID
    )
    assert candidate.reason.value == "selector_not_matched"


def test_temporal_comparison_resolves_each_admission_cycle_and_builds_diff() -> None:
    reader = _ReviewReader()
    resolver = EffectivePolicyResolver(
        policies=reader,
        admission_cycles=_CycleReader(),
        domain_readers=(_OwnerReader(),),
        clock=_Clock(),
    )

    comparison = resolver.compare_for_claims(
        PolicyResolutionRequest(
            university_id=UNIVERSITY_ID,
            admission_year=2027,
            as_known_at=NOW,
        ),
        (2027, 2028),
        CURRENT_REVISION.source_claims,
    )

    assert comparison.before_trace.valid_as_of == datetime(2027, 6, 1, tzinfo=UTC)
    assert comparison.after_trace.valid_as_of == datetime(2028, 6, 1, tzinfo=UTC)
    assert comparison.before_trace.effective_rules == ()
    assert tuple(item.rule_id for item in comparison.after_trace.effective_rules) == (
        CURRENT_RULE_ID,
    )
    assert comparison.diff.before_trace_id == comparison.before_trace.trace_id
    assert comparison.diff.after_trace_id == comparison.after_trace.trace_id
    assert reader.write_calls == 0
