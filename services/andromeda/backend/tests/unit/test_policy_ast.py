from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    ClaimRevisionRef,
    EvidenceLocator,
    EvidenceRef,
    SourceMilestones,
    TemporalInterval,
)
from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalCapability,
    PolicyApprovalCommand,
    PolicyApprovalEventKind,
    PolicyApprovalState,
    PolicyRuleSubmission,
)
from andromeda.modules.policy.contracts.public import (
    DomainRuleRef,
    PolicyContextField,
    PolicyDomainOwner,
    PolicyRevisionLifecycle,
    PolicyScope,
    PolicyScopeLevel,
    PolicySelectorAst,
    PolicySelectorNode,
    PolicySelectorNodeKind,
)
from andromeda.modules.policy.contracts.rule import (
    PolicyAuthorityLevel,
    PolicyRuleRevisionFields,
)
from andromeda.modules.policy.contracts.temporal import PolicyTemporalRevision
from andromeda.modules.policy.domain.approval import (
    create_approval_event,
    create_pending_submission_event,
    derive_approval_state,
)
from andromeda.modules.policy.domain.rule import create_policy_rule_revision
from andromeda.modules.policy.services.approval import PolicyApprovalCommandService

NOW = datetime(2027, 12, 15, 12, tzinfo=UTC)
FUTURE = datetime(2028, 9, 1, tzinfo=UTC)


def _selector() -> PolicySelectorAst:
    return PolicySelectorAst(
        nodes=(
            PolicySelectorNode(
                node_id="university",
                kind=PolicySelectorNodeKind.EQUALS,
                field=PolicyContextField.UNIVERSITY_ID,
                value="university:bmstu",
            ),
        )
    )


def _revision_fields() -> PolicyRuleRevisionFields:
    return PolicyRuleRevisionFields(
        rule_id="policy-rule:fourth-exam-route",
        revision=1,
        family_id="policy-family:admission-benefit",
        authority=PolicyAuthorityLevel.UNIVERSITY_NORMATIVE,
        selector=_selector(),
        scope=PolicyScope(level=PolicyScopeLevel.UNIVERSITY, scope_id="university:bmstu"),
        domain_rule=DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            canonical_rule_id="admission-benefit:olympiad-confirmation",
            owner_revision=1,
        ),
        lifecycle=PolicyRevisionLifecycle.FUTURE_EFFECTIVE,
        temporal=PolicyTemporalRevision(
            clock=BitemporalRevision(
                revision=1,
                valid_time=TemporalInterval(start=FUTURE),
                recorded_at=NOW,
            ),
            source_milestones=SourceMilestones(
                published_at=NOW,
                captured_at=NOW,
                effective_time=TemporalInterval(start=FUTURE),
            ),
        ),
        source_claims=(ClaimRevisionRef(claim_id="claim:" + "a" * 64, revision=1),),
        evidence=(
            EvidenceRef(
                source_id="source:bmstu-admission",
                source_observation_id="source-observation:" + "b" * 32,
                snapshot_sha256="c" * 64,
                source_url="https://priem.bmstu.ru/admission/order.pdf",
                locator=EvidenceLocator(page=2, section="Olympiad confirmation"),
            ),
        ),
    )


def test_selector_ast_is_closed_typed_bounded_and_deterministic() -> None:
    fields = _revision_fields()
    first = create_policy_rule_revision(fields)
    second = create_policy_rule_revision(fields)

    assert first.content_hash == second.content_hash
    assert first.domain_rule.owner_module is PolicyDomainOwner.ADMISSION_BENEFITS
    assert first.domain_rule.canonical_rule_id.startswith("admission-benefit:")
    assert first.lifecycle is PolicyRevisionLifecycle.FUTURE_EFFECTIVE
    assert first.content_hash == first.model_copy(update={"content_hash": first.content_hash}).content_hash


def test_selector_rejects_unknown_fields_wrong_scalar_types_and_unbounded_tree() -> None:
    with pytest.raises(ValidationError):
        PolicySelectorNode(
            node_id="unsafe",
            kind=PolicySelectorNodeKind.EQUALS,
            field="sql_statement",  # type: ignore[arg-type]
            value="DELETE FROM policy_rule_revisions",
        )

    with pytest.raises(ValidationError):
        PolicySelectorNode(
            node_id="year",
            kind=PolicySelectorNodeKind.EQUALS,
            field=PolicyContextField.ADMISSION_YEAR,
            value="2028",
        )

    with pytest.raises(ValidationError, match="depth cannot exceed 8"):
        PolicySelectorAst(
            nodes=(
                PolicySelectorNode(node_id="n0", kind=PolicySelectorNodeKind.ALL),
                PolicySelectorNode(
                    node_id="n1", parent_id="n0", kind=PolicySelectorNodeKind.ALL
                ),
                PolicySelectorNode(
                    node_id="leaf0",
                    parent_id="n0",
                    kind=PolicySelectorNodeKind.EXISTS,
                    field=PolicyContextField.PROGRAM_ID,
                ),
                PolicySelectorNode(
                    node_id="n2", parent_id="n1", kind=PolicySelectorNodeKind.ALL
                ),
                PolicySelectorNode(
                    node_id="leaf1",
                    parent_id="n1",
                    kind=PolicySelectorNodeKind.EXISTS,
                    field=PolicyContextField.PROGRAM_ID,
                ),
                PolicySelectorNode(
                    node_id="n3", parent_id="n2", kind=PolicySelectorNodeKind.ALL
                ),
                PolicySelectorNode(
                    node_id="leaf2",
                    parent_id="n2",
                    kind=PolicySelectorNodeKind.EXISTS,
                    field=PolicyContextField.PROGRAM_ID,
                ),
                PolicySelectorNode(
                    node_id="n4", parent_id="n3", kind=PolicySelectorNodeKind.ALL
                ),
                PolicySelectorNode(
                    node_id="leaf3",
                    parent_id="n3",
                    kind=PolicySelectorNodeKind.EXISTS,
                    field=PolicyContextField.PROGRAM_ID,
                ),
                PolicySelectorNode(
                    node_id="n5", parent_id="n4", kind=PolicySelectorNodeKind.ALL
                ),
                PolicySelectorNode(
                    node_id="leaf4",
                    parent_id="n4",
                    kind=PolicySelectorNodeKind.EXISTS,
                    field=PolicyContextField.PROGRAM_ID,
                ),
                PolicySelectorNode(
                    node_id="n6", parent_id="n5", kind=PolicySelectorNodeKind.ALL
                ),
                PolicySelectorNode(
                    node_id="leaf5",
                    parent_id="n5",
                    kind=PolicySelectorNodeKind.EXISTS,
                    field=PolicyContextField.PROGRAM_ID,
                ),
                PolicySelectorNode(
                    node_id="n7", parent_id="n6", kind=PolicySelectorNodeKind.ALL
                ),
                PolicySelectorNode(
                    node_id="leaf6",
                    parent_id="n6",
                    kind=PolicySelectorNodeKind.EXISTS,
                    field=PolicyContextField.PROGRAM_ID,
                ),
                PolicySelectorNode(
                    node_id="leaf7a",
                    parent_id="n7",
                    kind=PolicySelectorNodeKind.EXISTS,
                    field=PolicyContextField.PROGRAM_ID,
                ),
                PolicySelectorNode(
                    node_id="leaf7b",
                    parent_id="n7",
                    kind=PolicySelectorNodeKind.EXISTS,
                    field=PolicyContextField.DIRECTION_ID,
                ),
            )
        )


def test_domain_rule_owner_namespace_and_non_source_evidence_fail_closed() -> None:
    with pytest.raises(ValidationError, match="namespace"):
        DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            canonical_rule_id="admission:some-rule",
            owner_revision=1,
        )

    fields = _revision_fields().model_copy(
        update={
            "evidence": (
                EvidenceRef(
                    source_id="source:bmstu-admission",
                    source_observation_id="source-observation:" + "b" * 32,
                    snapshot_sha256="c" * 64,
                    source_url="https://priem.bmstu.ru/admission/order.pdf",
                    locator=EvidenceLocator(page=2),
                    inferred=True,
                ),
            )
        }
    )
    with pytest.raises(ValidationError, match="must not be inferred"):
        create_policy_rule_revision(fields)


def test_approval_history_is_exact_revision_bound_and_terminal() -> None:
    revision = create_policy_rule_revision(_revision_fields())
    pending = create_pending_submission_event(
        revision,
        actor_account_id="account:" + "d" * 32,
        reason="Staged by a policy steward for exact human review.",
        recorded_at=NOW,
    )
    assert derive_approval_state(
        (pending,),
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
    ) is PolicyApprovalState.PENDING

    approved = create_approval_event(
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
        sequence=2,
        kind=PolicyApprovalEventKind.APPROVED,
        actor_account_id="account:" + "e" * 32,
        reason="Exact source-backed revision reviewed.",
        recorded_at=datetime(2027, 12, 15, 12, 1, tzinfo=UTC),
        preview_fingerprint="a" * 64,
    )
    assert approved.capability is PolicyApprovalCapability.APPROVE_REVISION
    assert derive_approval_state(
        (pending, approved),
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
    ) is PolicyApprovalState.APPROVED
    assert derive_approval_state(
        (pending, approved),
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash="f" * 64,
    ) is PolicyApprovalState.INVALID


def test_policy_approval_command_requires_exact_preview_fingerprint() -> None:
    revision = create_policy_rule_revision(_revision_fields())

    with pytest.raises(ValidationError, match="exact reviewer preview fingerprint"):
        PolicyApprovalCommand(
            rule_id=revision.rule_id,
            revision=revision.revision,
            revision_hash=revision.content_hash,
            kind=PolicyApprovalEventKind.APPROVED,
            actor_account_id="account:" + "e" * 32,
            reason="Attempt approval without a reviewed impact preview.",
            recorded_at=datetime(2027, 12, 15, 12, 1, tzinfo=UTC),
        )


def test_policy_mutations_require_the_specific_capability_before_repository_write() -> None:
    revision = create_policy_rule_revision(_revision_fields())
    submission = PolicyRuleSubmission(
        revision=revision,
        submitted_by_account_id="account:" + "d" * 32,
        reason="Prepare exact rule revision for review.",
        submitted_at=datetime(2027, 12, 15, 12, 2, tzinfo=UTC),
    )

    class DenyAuthorizer:
        def require_capability(self, actor_account_id: str, capability: PolicyApprovalCapability) -> None:
            assert actor_account_id == submission.submitted_by_account_id
            assert capability is PolicyApprovalCapability.SUBMIT_REVISION
            raise PermissionError("missing policy.submit_revision")

    class NeverWriteRepository:
        def submit_revision(self, _submission: PolicyRuleSubmission) -> object:
            raise AssertionError("denied actor reached policy repository")

    class UnitOfWork:
        committed = 0
        rolled_back = 0

        def commit(self) -> None:
            self.committed += 1

        def rollback(self) -> None:
            self.rolled_back += 1

    unit_of_work = UnitOfWork()
    service = PolicyApprovalCommandService(
        repository=NeverWriteRepository(),  # type: ignore[arg-type]
        authorizer=DenyAuthorizer(),  # type: ignore[arg-type]
        unit_of_work=unit_of_work,
    )

    with pytest.raises(PermissionError, match="policy.submit_revision"):
        service.submit(submission)
    assert unit_of_work.committed == 0
    assert unit_of_work.rolled_back == 0
