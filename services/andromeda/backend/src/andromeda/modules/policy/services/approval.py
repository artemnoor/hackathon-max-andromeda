"""Capability-gated commands for immutable policy revision and approval writes."""

from __future__ import annotations

from typing import Protocol

from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalCapability,
    PolicyApprovalCommand,
    PolicyApprovalEvent,
    PolicyApprovalEventKind,
    PolicyApprovalState,
    PolicyRuleSubmission,
)
from andromeda.modules.policy.contracts.rule import (
    PolicyDomainOwner,
    PolicyRuleRevision,
)
from andromeda.modules.policy.contracts.what_if import PolicyHypotheticalPreview
from andromeda.modules.policy.domain.approval import (
    create_approval_event,
    derive_approval_state,
)
from andromeda.modules.policy.domain.field_registry import validate_selector_ast
from andromeda.modules.policy.domain.relations import validate_policy_relations
from andromeda.modules.policy.repository.ports import (
    PolicyApprovalConflictReader,
    PolicyCapabilityAuthorizer,
    PolicyRuleRepository,
)
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)


class PolicyApprovalUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PolicyApprovalCommandService:
    """Authorize all mutations and keep revision+pending-event writes atomic."""

    def __init__(
        self,
        *,
        repository: PolicyRuleRepository,
        authorizer: PolicyCapabilityAuthorizer,
        unit_of_work: PolicyApprovalUnitOfWork,
        approval_conflicts: PolicyApprovalConflictReader | None = None,
    ) -> None:
        self._repository = repository
        self._authorizer = authorizer
        self._unit_of_work = unit_of_work
        self._approval_conflicts = approval_conflicts

    def submit(self, submission: PolicyRuleSubmission) -> PolicyApprovalEvent:
        self._authorizer.require_capability(
            submission.submitted_by_account_id,
            PolicyApprovalCapability.SUBMIT_REVISION,
        )
        revision = submission.revision
        if revision.schema_version not in {"policy-rule.v2", "policy-rule.v3"}:
            raise ValidationError(
                "new policy submissions must use policy-rule.v2 or policy-rule.v3"
            )
        if (
            revision.domain_rule.owner_module
            in {PolicyDomainOwner.ADMISSION_BENEFITS, PolicyDomainOwner.ADMISSIONS}
            and revision.schema_version != "policy-rule.v3"
        ):
            raise ValidationError(
                "admissions domain policy references require exact policy-rule.v3 owner hashes"
            )
        validate_selector_ast(submission.revision.selector)
        try:
            self._validate_relations(revision)
            event = self._repository.submit_revision(submission)
            self._unit_of_work.commit()
            return event
        except Exception:
            self._unit_of_work.rollback()
            raise

    def _validate_relations(self, revision: PolicyRuleRevision) -> None:
        if not revision.relations:
            return
        approved_revisions = self._repository.list_approved_revisions(
            as_known_at=revision.temporal.clock.recorded_at
        )
        approved_by_identity = {
            (item.rule_id, item.revision, item.content_hash): item
            for item in approved_revisions
        }
        approved_targets: list[PolicyRuleRevision] = []
        for relation in revision.relations:
            persisted_target = self._repository.get_revision(
                relation.target_rule_id,
                relation.target_revision,
            )
            if persisted_target is None:
                raise NotFoundError(
                    "Policy relation references an unknown target revision"
                )
            if persisted_target.content_hash != relation.target_hash:
                raise ConflictError(
                    "Policy relation target hash does not match its exact revision"
                )
            approved_target = approved_by_identity.get(
                (
                    relation.target_rule_id,
                    relation.target_revision,
                    relation.target_hash,
                )
            )
            if approved_target is None:
                raise ValidationError(
                    "Policy relation target must already be approved at revision time"
                )
            approved_targets.append(approved_target)
        try:
            validate_policy_relations(
                revision,
                approved_targets=tuple(approved_targets),
                approved_revisions=approved_revisions,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def decide(
        self,
        command: PolicyApprovalCommand,
        *,
        review_preview: PolicyHypotheticalPreview | None = None,
    ) -> PolicyApprovalEvent:
        self._authorizer.require_capability(
            command.actor_account_id,
            PolicyApprovalCapability.APPROVE_REVISION,
        )
        try:
            if command.kind is PolicyApprovalEventKind.APPROVED:
                if review_preview is None:
                    raise ValidationError(
                        "Policy approval must pass through the reviewed preview gate"
                    )
                self._require_approval_readiness(command, review_preview)
        except Exception:
            self._unit_of_work.rollback()
            raise
        return self._append_decision(command)

    def _append_decision(self, command: PolicyApprovalCommand) -> PolicyApprovalEvent:
        try:
            revision = self._repository.get_revision(command.rule_id, command.revision)
            if revision is None:
                raise NotFoundError("Policy rule revision does not exist")
            if revision.content_hash != command.revision_hash:
                raise ConflictError("Policy decision is bound to a stale revision hash")
            history = self._repository.list_approval_events(command.rule_id, command.revision)
            state = derive_approval_state(
                history,
                rule_id=command.rule_id,
                revision=command.revision,
                revision_hash=revision.content_hash,
            )
            if state is not PolicyApprovalState.PENDING:
                latest = history[-1] if history else None
                repeated_state = {
                    PolicyApprovalEventKind.APPROVED: PolicyApprovalState.APPROVED,
                    PolicyApprovalEventKind.REJECTED: PolicyApprovalState.REJECTED,
                    PolicyApprovalEventKind.WITHDRAWN: PolicyApprovalState.WITHDRAWN,
                }[command.kind]
                if (
                    state is repeated_state
                    and latest is not None
                    and latest.kind is command.kind
                    and latest.actor_account_id == command.actor_account_id
                    and latest.reason == command.reason
                    and latest.recorded_at == command.recorded_at
                    and latest.revision_hash == command.revision_hash
                    and latest.preview_fingerprint == command.preview_fingerprint
                ):
                    self._unit_of_work.commit()
                    return latest
                raise ConflictError("Only a valid pending policy revision can receive a decision")
            event = create_approval_event(
                rule_id=command.rule_id,
                revision=command.revision,
                revision_hash=revision.content_hash,
                sequence=len(history) + 1,
                kind=command.kind,
                actor_account_id=command.actor_account_id,
                reason=command.reason,
                recorded_at=command.recorded_at,
                preview_fingerprint=command.preview_fingerprint,
            )
            appended = self._repository.append_approval_event(event)
            self._unit_of_work.commit()
            return appended
        except Exception:
            self._unit_of_work.rollback()
            raise

    def _require_approval_readiness(
        self,
        command: PolicyApprovalCommand,
        review_preview: PolicyHypotheticalPreview,
    ) -> None:
        if self._approval_conflicts is None:
            raise ValidationError(
                "Policy approval requires a verified preview and conflict reader"
            )
        try:
            preview = PolicyHypotheticalPreview.model_validate(
                review_preview.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ConflictError("Policy approval preview is invalid") from exc
        if (
            preview.target.rule_id != command.rule_id
            or preview.target.revision != command.revision
            or preview.target.revision_hash != command.revision_hash
        ):
            raise ConflictError("Policy approval preview targets a different revision")
        preview_fingerprint = preview.preview_id.partition(":")[2]
        if preview_fingerprint != command.preview_fingerprint:
            raise ConflictError("Policy approval preview fingerprint is stale")
        if preview.candidate_trace.status.value != "resolved":
            raise ConflictError("Policy candidate applicability is unresolved")
        if preview.impact.status.value != "complete":
            raise ConflictError("Complete domain-owner impact is required before approval")
        if self._approval_conflicts.has_open_conflicts(
            command.rule_id,
            command.revision,
            command.revision_hash,
        ):
            raise ConflictError("Policy approval is blocked by an unresolved conflict")


__all__ = ["PolicyApprovalCommandService", "PolicyApprovalUnitOfWork"]
