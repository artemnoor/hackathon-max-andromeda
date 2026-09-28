from __future__ import annotations

import logging

from andromeda.modules.knowledge.contracts.review import (
    KnowledgeReviewCapability,
    KnowledgeReviewTargetRef,
)
from andromeda.modules.knowledge.repository.ports import KnowledgeReviewAuthorizer
from andromeda.modules.policy.contracts.approval import PolicyApprovalCapability
from andromeda.modules.policy.repository.ports import PolicyCapabilityAuthorizer
from andromeda.shared.contracts.errors import NotFoundError

logger = logging.getLogger("andromeda.infrastructure.knowledge_review_auth")


class ConfiguredKnowledgeReviewAuthorizer(KnowledgeReviewAuthorizer):
    """Explicit central reviewer allowlist; empty configuration denies review writes."""

    def __init__(self, reviewer_account_ids: tuple[str, ...]) -> None:
        self._reviewers = frozenset(reviewer_account_ids)

    def require_capability(
        self,
        actor_account_id: str,
        capability: KnowledgeReviewCapability,
        target: KnowledgeReviewTargetRef,
    ) -> None:
        if actor_account_id not in self._reviewers:
            logger.warning(
                "knowledge_review_access_denied actor_account_id=%s capability=%s target_kind=%s",
                actor_account_id,
                capability.value,
                target.kind.value,
            )
            raise NotFoundError("Resource was not found")


class ConfiguredPolicyStewardAuthorizer(PolicyCapabilityAuthorizer):
    """Policy approval is restricted to a separate central policy-steward allowlist."""

    def __init__(self, policy_steward_account_ids: tuple[str, ...]) -> None:
        self._stewards = frozenset(policy_steward_account_ids)

    def require_capability(
        self,
        actor_account_id: str,
        capability: PolicyApprovalCapability,
    ) -> None:
        if (
            capability is not PolicyApprovalCapability.APPROVE_REVISION
            or actor_account_id not in self._stewards
        ):
            logger.warning(
                "policy_steward_access_denied actor_account_id=%s capability=%s",
                actor_account_id,
                capability.value,
            )
            raise NotFoundError("Resource was not found")


__all__ = [
    "ConfiguredKnowledgeReviewAuthorizer",
    "ConfiguredPolicyStewardAuthorizer",
]
