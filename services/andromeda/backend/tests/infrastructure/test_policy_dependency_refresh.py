from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import PolicyProjectionRefreshModel
from andromeda.infrastructure.repositories.policy_refresh import (
    SqlAlchemyPolicyProjectionRefreshRepository,
)
from andromeda.modules.policy.contracts.applicability import PolicySelection
from andromeda.modules.policy.contracts.dependencies import (
    PolicyDependencyNode,
    PolicyDependencyNodeKind,
)
from andromeda.modules.policy.contracts.impact import (
    ImpactActionability,
    ImpactAffectedObject,
    ImpactReason,
    PolicyImpactPreview,
    PolicyImpactPreviewFields,
    PolicyImpactStatus,
    policy_impact_id,
)
from andromeda.modules.policy.contracts.refresh import (
    PolicyProjectionKind,
    PolicyProjectionRefreshCommand,
    PolicyProjectionRefreshOutcome,
    PolicyProjectionRefreshRecord,
    PolicyProjectionRefreshState,
    policy_projection_refresh_key,
)
from andromeda.modules.policy.contracts.rule import (
    DomainRuleRef,
    PolicyDomainOwner,
    PolicyRuleRevision,
)
from andromeda.modules.policy.services.dependency_refresh import (
    PolicyDependencyRefreshService,
)
from andromeda.shared.contracts.errors import ConflictError

NOW = datetime(2028, 9, 1, tzinfo=UTC)


def _selection(revision: int = 1) -> PolicySelection:
    return PolicySelection(
        rule_id="policy-rule:refresh-test",
        revision=revision,
        revision_hash=str(revision) * 64,
        domain_rule=DomainRuleRef(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            canonical_rule_id="admission-benefit:refresh-test",
            owner_revision=revision,
        ),
    )


def _command(selection: PolicySelection) -> PolicyProjectionRefreshCommand:
    return PolicyProjectionRefreshCommand(
        target=PolicyDependencyNode(
            kind=PolicyDependencyNodeKind.SCOPE,
            object_id="program:bmstu:09.03.01-01",
        ),
        projection_kind=PolicyProjectionKind.EFFECTIVE_POLICY,
        invalidated_by=(selection,),
        invalidated_at=NOW,
    )


def _impact() -> PolicyImpactPreview:
    fields = PolicyImpactPreviewFields(
        university_id="university:bmstu",
        admission_year=2028,
        context_fingerprint="a" * 64,
        current_trace_id="policy-resolution:" + "c" * 64,
        candidate_trace_id="policy-resolution:" + "d" * 64,
        policy_diff_id="policy-diff:" + "b" * 64,
        status=PolicyImpactStatus.COMPLETE,
        actionability=ImpactActionability.INFORMATIONAL,
        reason=ImpactReason.POLICY_CHANGE_INFORMATIONAL,
        affected_objects=(
            ImpactAffectedObject(
                node=PolicyDependencyNode(
                    kind=PolicyDependencyNodeKind.SCOPE,
                    object_id="program:bmstu:09.03.01-01",
                ),
                relation_path=(),
            ),
        ),
        calculated_at=NOW,
    )
    return PolicyImpactPreview(**fields.model_dump(mode="python"), impact_id=policy_impact_id(fields))


class _ApprovedReader:
    def get_approved_revision(
        self,
        rule_id: str,
        revision: int,
        *,
        as_known_at: datetime | None = None,
    ) -> PolicyRuleRevision | None:
        selection = _selection(revision)
        if rule_id != selection.rule_id or revision != 1:
            return None
        return cast(PolicyRuleRevision, SimpleNamespace(content_hash=selection.revision_hash))

    def list_approved_revisions(self, *, as_known_at: datetime) -> tuple[PolicyRuleRevision, ...]:
        return ()


class _ProjectionBuilder:
    def rebuild(self, record: PolicyProjectionRefreshRecord) -> str:
        return "c" * 64


def test_projection_refresh_is_idempotent_and_rejects_stale_generation(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'policy-refresh.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            repository = SqlAlchemyPolicyProjectionRefreshRepository(session)
            first = _command(_selection(1))
            initial = repository.mark_dirty(first)
            repeated = repository.mark_dirty(first)
            assert repeated.generation == initial.generation == 1

            newer = repository.mark_dirty(_command(_selection(2)))
            assert newer.generation == 2
            assert newer.state is PolicyProjectionRefreshState.DIRTY

            stale = repository.record_success(
                newer.refresh_key,
                generation=1,
                projection_version="d" * 64,
                recorded_at=NOW,
            )
            assert stale.generation == 2
            assert stale.state is PolicyProjectionRefreshState.DIRTY

            failed = repository.record_failure(
                newer.refresh_key,
                generation=2,
                failure_code="rebuild_failed",
                recorded_at=NOW,
            )
            assert failed.state is PolicyProjectionRefreshState.FAILED
            assert repository.list_dirty() == (failed,)

            ready = repository.record_success(
                newer.refresh_key,
                generation=2,
                projection_version="e" * 64,
                recorded_at=NOW,
            )
            assert ready.state is PolicyProjectionRefreshState.READY
            assert ready.completed_generation == 2
            attempts = repository.list_attempts(newer.refresh_key)
            assert [item.outcome for item in attempts] == [
                PolicyProjectionRefreshOutcome.STALE_RESULT_REJECTED,
                PolicyProjectionRefreshOutcome.FAILED,
                PolicyProjectionRefreshOutcome.COMPLETED,
            ]
            session.commit()
    finally:
        engine.dispose()


def test_refresh_service_marks_only_approved_exact_policy_dependencies(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'policy-refresh-service.db').as_posix()}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            repository = SqlAlchemyPolicyProjectionRefreshRepository(session)
            service = PolicyDependencyRefreshService(
                repository=repository,
                approved_rules=_ApprovedReader(),
                builder=_ProjectionBuilder(),
            )
            records = service.mark_approved_impact_dirty(
                impact=_impact(),
                invalidated_by=(_selection(1),),
                invalidated_at=NOW,
            )
            assert len(records) == 4
            assert all(item.generation == 1 for item in records)
            assert len(repository.list_dirty()) == 4

            with pytest.raises(ConflictError):
                service.mark_approved_impact_dirty(
                    impact=_impact(),
                    invalidated_by=(_selection(2),),
                    invalidated_at=NOW,
                )
            assert session.query(PolicyProjectionRefreshModel).count() == 4

            refreshed = service.refresh_pending(limit=4)
            assert len(refreshed) == 4
            assert all(item.state is PolicyProjectionRefreshState.READY for item in refreshed)
            session.commit()
    finally:
        engine.dispose()


def test_refresh_key_is_bound_to_typed_target_and_projection_kind() -> None:
    command = _command(_selection())
    assert command.invalidated_by == (_selection(),)
    assert policy_projection_refresh_key(command.projection_kind, command.target)
