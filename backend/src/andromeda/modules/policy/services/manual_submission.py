"""University-scoped manual policy proposals through the policy approval owner."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from andromeda.modules.policy.contracts.approval import (
    PolicyApprovalEvent,
    PolicyRuleSubmission,
)
from andromeda.modules.policy.contracts.rule import (
    PolicyRuleRevision,
    PolicyScopeLevel,
)
from andromeda.modules.policy.services.approval import PolicyApprovalCommandService
from andromeda.shared.contracts.errors import ConflictError, ValidationError


class UniversityPolicyCandidateAuthorization(Protocol):
    def require_university_editor(self, actor_account_id: str, university_id: str) -> None: ...


class ManualPolicyCandidateCommands:
    """Submit pending university revisions; this service cannot approve them."""

    def __init__(
        self,
        *,
        approval_commands: PolicyApprovalCommandService,
        authorizer: UniversityPolicyCandidateAuthorization,
    ) -> None:
        self._approval_commands = approval_commands
        self._authorizer = authorizer

    def submit(
        self,
        *,
        actor_account_id: str,
        university_id: str,
        revision: PolicyRuleRevision,
        reason: str,
        submitted_at: datetime,
    ) -> PolicyApprovalEvent:
        self._authorizer.require_university_editor(actor_account_id, university_id)
        if (
            revision.scope.level is not PolicyScopeLevel.UNIVERSITY
            or revision.scope.scope_id != university_id
        ):
            raise ValidationError(
                "University editors may submit only a rule scoped to their exact university"
            )
        event = self._approval_commands.submit(
            PolicyRuleSubmission(
                revision=revision,
                submitted_by_account_id=actor_account_id,
                reason=reason,
                submitted_at=submitted_at,
            )
        )
        if (
            event.actor_account_id != actor_account_id
            or event.reason != reason
        ):
            raise ConflictError("Policy revision already has a different immutable submission event")
        return event


__all__ = ["ManualPolicyCandidateCommands", "UniversityPolicyCandidateAuthorization"]
