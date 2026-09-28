from __future__ import annotations

from datetime import UTC, datetime

from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    ClaimRevisionRef,
    EvidenceLocator,
    EvidenceRef,
    SourceMilestones,
    TemporalInterval,
)
from andromeda.modules.policy.contracts.applicability import (
    PolicyScopeMatchReason,
    PolicyScopeMatchState,
    PolicySelection,
)
from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalEventKind,
    PolicyApprovalEventReference,
    PolicyApprovalState,
    policy_approval_event_id,
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
    DiffObjectState,
    PolicyDiffChangeKind,
    PolicyDiffEntry,
    PolicyDiffStatus,
)
from andromeda.modules.policy.contracts.temporal import PolicyTemporalRevision
from andromeda.modules.policy.services.semantic_diff import (
    build_effective_policy_diff,
    build_policy_revision_diff,
)

CAPTURED = datetime(2027, 12, 15, tzinfo=UTC)
RECORDED = datetime(2027, 12, 16, tzinfo=UTC)
EVIDENCE = EvidenceRef(
    source_id="source:official-rules",
    source_observation_id="source-observation:" + "1" * 32,
    snapshot_sha256="2" * 64,
    source_url="https://official.example/rules.pdf",
    locator=EvidenceLocator(page=4, section="Admission rules"),
)


def _approval_reference(
    rule_id: str, revision: int, revision_hash: str
) -> PolicyApprovalEventReference:
    fingerprint = "b" * 64
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
        recorded_at=RECORDED,
    )


def _revision(
    *,
    revision: int = 1,
    minimum_owner_revision: int = 3,
    scope: PolicyScope | None = None,
) -> PolicyRuleRevision:
    fields = PolicyRuleRevisionFields(
        rule_id="policy-rule:bmstu-fourth-exam",
        revision=revision,
        family_id="policy-family:fourth-exam-benefit",
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        selector=PolicySelectorAst(
            nodes=(
                PolicySelectorNode(
                    node_id="university",
                    kind=PolicySelectorNodeKind.EQUALS,
                    field=PolicyContextField.UNIVERSITY_ID,
                    value="university:bmstu",
                ),
            )
        ),
        scope=scope
        or PolicyScope(level=PolicyScopeLevel.UNIVERSITY, scope_id="university:bmstu"),
        domain_rule=DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            canonical_rule_id="admission-benefit:fourth-exam",
            owner_revision=minimum_owner_revision,
        ),
        lifecycle=PolicyRevisionLifecycle.FUTURE_EFFECTIVE,
        temporal=PolicyTemporalRevision(
            clock=BitemporalRevision(
                revision=revision,
                valid_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
                recorded_at=RECORDED,
            ),
            source_milestones=SourceMilestones(
                captured_at=CAPTURED,
                effective_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
            ),
        ),
        source_claims=(ClaimRevisionRef(claim_id="claim:" + "a" * 64, revision=1),),
        evidence=(EVIDENCE,),
    )
    return PolicyRuleRevision(
        **fields.model_dump(mode="python"),
        content_hash=policy_rule_content_hash(fields),
    )


def _revise(base: PolicyRuleRevision, **changes: object) -> PolicyRuleRevision:
    values = base.model_dump(mode="python", exclude={"content_hash"})
    values.update(changes)
    fields = PolicyRuleRevisionFields(**values)
    return PolicyRuleRevision(
        **fields.model_dump(mode="python"),
        content_hash=policy_rule_content_hash(fields),
    )


def test_policy_diff_explains_scope_and_domain_revision_changes_with_evidence() -> None:
    before = _revision()
    after = _revise(
        before,
        revision=2,
        domain_rule=DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            canonical_rule_id="admission-benefit:fourth-exam",
            owner_revision=4,
        ),
        scope=PolicyScope(level=PolicyScopeLevel.DIRECTION, scope_id="direction:01.03.02"),
        temporal=PolicyTemporalRevision(
            clock=BitemporalRevision(
                revision=2,
                valid_time=TemporalInterval(start=datetime(2028, 9, 1, tzinfo=UTC)),
                recorded_at=datetime(2027, 12, 17, tzinfo=UTC),
            ),
            source_milestones=before.temporal.source_milestones,
        ),
    )

    diff = build_policy_revision_diff(
        before=before,
        after=after,
        before_approval=PolicyApprovalState.APPROVED,
        after_approval=PolicyApprovalState.PENDING,
        before_normalizer_version="policy-rule.v2",
        after_normalizer_version="policy-rule.v3",
        domain_owner_changes=(
            PolicyDiffEntry(
                path="domain_owner.minimum_score",
                kind=PolicyDiffChangeKind.CHANGED,
                before="75",
                after="80",
                before_evidence=(EVIDENCE,),
                after_evidence=(EVIDENCE,),
                reason_code="typed_domain_rule_change",
            ),
            PolicyDiffEntry(
                path="domain_owner.benefit_kind",
                kind=PolicyDiffChangeKind.CHANGED,
                before="bvi",
                after="100_points",
                before_evidence=(EVIDENCE,),
                after_evidence=(EVIDENCE,),
                reason_code="typed_domain_rule_change",
            ),
        ),
    )

    changes = {item.path: item for item in diff.changes}
    assert diff.status is PolicyDiffStatus.COMPLETE
    assert changes["scope.level"].kind is PolicyDiffChangeKind.CHANGED
    assert changes["scope.id"].after == '"direction:01.03.02"'
    assert changes["domain_rule.revision"].after == "4"
    assert changes["approval_state"].before == '"approved"'
    assert changes["normalizer_version"].before == '"policy-rule.v2"'
    assert changes["scope.id"].before_evidence == (EVIDENCE,)
    assert changes["scope.id"].after_evidence == (EVIDENCE,)
    assert changes["domain_owner.minimum_score"].before == "75"
    assert changes["domain_owner.minimum_score"].after == "80"
    assert changes["domain_owner.benefit_kind"].before == "bvi"
    assert changes["domain_owner.benefit_kind"].after == "100_points"


def test_missing_prior_revision_is_incomplete_not_an_inferred_deletion() -> None:
    diff = build_policy_revision_diff(
        before=None,
        after=_revision(),
        before_state=DiffObjectState.UNKNOWN,
        after_state=DiffObjectState.PRESENT,
    )

    assert diff.status is PolicyDiffStatus.INCOMPLETE
    assert diff.changes == ()
    assert diff.uncertainty_codes == ("revision_presence_unknown",)


def test_confirmed_absence_and_selector_schema_are_explicit_in_diff() -> None:
    after = _revision()
    added = build_policy_revision_diff(
        before=None,
        after=after,
        before_state=DiffObjectState.ABSENT_CONFIRMED,
        after_state=DiffObjectState.PRESENT,
    )
    assert added.status is PolicyDiffStatus.COMPLETE
    assert all(item.kind is PolicyDiffChangeKind.ADDED for item in added.changes)

    same_revision_new_parser = build_policy_revision_diff(
        before=after,
        after=after,
        before_approval=PolicyApprovalState.PENDING,
        after_approval=PolicyApprovalState.PENDING,
        before_normalizer_version="parser-v1",
        after_normalizer_version="parser-v2",
    )
    assert {
        item.path for item in same_revision_new_parser.changes
    } == {"normalizer_version"}


def test_effective_policy_diff_is_typed_across_cohorts_and_retains_trace_evidence() -> None:
    revision = _revision()

    def trace(admission_year: int, *, selected: bool) -> ResolutionTrace:
        selection = PolicySelection(
            rule_id=revision.rule_id,
            revision=revision.revision,
            revision_hash=revision.content_hash,
            domain_rule=revision.domain_rule,
        )
        considered = ConsideredPolicyRule(
            rule_id=revision.rule_id,
            revision=revision.revision,
            revision_hash=revision.content_hash,
            lifecycle=revision.lifecycle,
            valid_interval=(datetime(2028, 9, 1, tzinfo=UTC), None),
            effective_interval=(datetime(2028, 9, 1, tzinfo=UTC), None),
            domain_rule=revision.domain_rule,
            family_id=revision.family_id,
            authority=revision.authority,
            scope=revision.scope,
            scope_state=PolicyScopeMatchState.MATCH,
            scope_reason=PolicyScopeMatchReason.CONTEXT_MATCHED,
            evidence=revision.evidence,
            approval_event=_approval_reference(
                revision.rule_id, revision.revision, revision.content_hash
            ),
            filter_state=(
                PolicyRuleFilterState.CANDIDATE
                if selected
                else PolicyRuleFilterState.FUTURE
            ),
            reason=(
                PolicyRuleFilterReason.SELECTOR_MATCHED
                if selected
                else PolicyRuleFilterReason.FUTURE_EFFECTIVE
            ),
            selector_trace=(),
            selection=selection if selected else None,
        )
        fields = ResolutionTraceFields(
            university_id="university:bmstu",
            admission_year=admission_year,
            valid_as_of=datetime(2028, 9, 1, tzinfo=UTC),
            as_known_at=RECORDED,
            context_fingerprint=(str(admission_year) + "a" * 64)[:64],
            status=(
                PolicyResolutionStatus.RESOLVED
                if selected
                else PolicyResolutionStatus.NO_MATCH
            ),
            considered=(considered,),
            candidates=(selection,) if selected else (),
            effective_rules=(selection,) if selected else (),
        )
        return ResolutionTrace(
            **fields.model_dump(mode="python"),
            trace_id=policy_resolution_trace_id(fields),
        )

    diff = build_effective_policy_diff(
        before=trace(2027, selected=False),
        after=trace(2028, selected=True),
    )

    changes = {item.path: item for item in diff.changes}
    assert diff.status is PolicyDiffStatus.COMPLETE
    assert changes["context.admission_year"].before == "2027"
    assert changes["context.admission_year"].after == "2028"
    effective_rule = changes[f"effective_rules.{revision.rule_id}"]
    assert effective_rule.kind is PolicyDiffChangeKind.ADDED
    assert effective_rule.after_evidence == revision.evidence
    assert diff.before_trace_id is not None
    assert diff.after_trace_id is not None


def test_policy_selector_diff_preserves_explicit_program_scope_set() -> None:
    before = _revision()
    selector = PolicySelectorAst(
        nodes=(
            PolicySelectorNode(node_id="root", kind=PolicySelectorNodeKind.ALL),
            PolicySelectorNode(
                node_id="university",
                parent_id="root",
                kind=PolicySelectorNodeKind.EQUALS,
                field=PolicyContextField.UNIVERSITY_ID,
                value="university:bmstu",
            ),
            PolicySelectorNode(
                node_id="programs",
                parent_id="root",
                kind=PolicySelectorNodeKind.IN,
                field=PolicyContextField.PROGRAM_ID,
                values=("program:01.03.02", "program:10.05.01", "program:27.03.04"),
            ),
        )
    )
    after = _revise(
        before,
        revision=2,
        selector=selector,
        temporal=PolicyTemporalRevision(
            clock=BitemporalRevision(
                revision=2,
                valid_time=before.temporal.clock.valid_time,
                recorded_at=datetime(2027, 12, 17, tzinfo=UTC),
            ),
            source_milestones=before.temporal.source_milestones,
        ),
    )

    diff = build_policy_revision_diff(before=before, after=after)

    selector_change = next(
        item for item in diff.changes if item.path == "selector.nodes.programs"
    )
    assert selector_change.kind is PolicyDiffChangeKind.ADDED
    assert all(program_id in selector_change.after for program_id in (
        "program:01.03.02",
        "program:10.05.01",
        "program:27.03.04",
    ))
