from __future__ import annotations

import logging

from andromeda.modules.knowledge.repository.ports import KnowledgeManualAuthorization
from andromeda.modules.policy.contracts.approval import PolicyApprovalCapability
from andromeda.modules.policy.repository.ports import PolicyCapabilityAuthorizer
from andromeda.modules.university_admin.contracts.public import UniversityAdminRole
from andromeda.modules.university_admin.services.access import (
    UniversityAdminAccessService,
)
from andromeda.shared.contracts.errors import NotFoundError

logger = logging.getLogger("andromeda.infrastructure.knowledge_manual_auth")


class ConfiguredKnowledgeManualAuthorization(KnowledgeManualAuthorization):
    """Bind source-steward capabilities to explicit human accounts; empty denies all."""

    def __init__(
        self,
        *,
        university_access: UniversityAdminAccessService,
        source_steward_account_ids: tuple[str, ...],
    ) -> None:
        self._university_access = university_access
        self._source_stewards = frozenset(source_steward_account_ids)

    def require_source_steward(self, actor_account_id: str) -> None:
        if actor_account_id not in self._source_stewards:
            logger.warning(
                "knowledge_source_steward_access_denied actor_account_id=%s",
                actor_account_id,
            )
            raise NotFoundError("Resource was not found")

    def require_university_editor(self, actor_account_id: str, university_id: str) -> None:
        self._university_access.require(
            actor_account_id,
            university_id,
            UniversityAdminRole.EDITOR,
        )


class UniversityPolicySubmissionOnlyAuthorizer(PolicyCapabilityAuthorizer):
    """Bind a policy command to one university editor and deny approval capability."""

    def __init__(
        self,
        *,
        university_access: UniversityAdminAccessService,
        actor_account_id: str,
        university_id: str,
    ) -> None:
        self._university_access = university_access
        self._actor_account_id = actor_account_id
        self._university_id = university_id

    def require_university_editor(self, actor_account_id: str, university_id: str) -> None:
        if actor_account_id != self._actor_account_id or university_id != self._university_id:
            raise NotFoundError("Resource was not found")
        self._university_access.require(
            actor_account_id,
            university_id,
            UniversityAdminRole.EDITOR,
        )

    def require_capability(
        self, actor_account_id: str, capability: PolicyApprovalCapability
    ) -> None:
        if (
            capability is not PolicyApprovalCapability.SUBMIT_REVISION
            or actor_account_id != self._actor_account_id
        ):
            raise NotFoundError("Resource was not found")
        self.require_university_editor(actor_account_id, self._university_id)


__all__ = [
    "ConfiguredKnowledgeManualAuthorization",
    "UniversityPolicySubmissionOnlyAuthorizer",
]
