from __future__ import annotations

import pytest

from andromeda.infrastructure.repositories.knowledge_review_auth import (
    ConfiguredKnowledgeReviewAuthorizer,
    ConfiguredPolicyStewardAuthorizer,
)
from andromeda.modules.knowledge.contracts.review import (
    KnowledgeReviewCapability,
    KnowledgeReviewTargetKind,
    KnowledgeReviewTargetRef,
)
from andromeda.modules.policy.contracts.approval import PolicyApprovalCapability
from andromeda.shared.contracts.errors import NotFoundError

REVIEWER = "account:" + "a" * 32
TARGET = KnowledgeReviewTargetRef(
    kind=KnowledgeReviewTargetKind.CLAIM,
    object_id="claim:" + "b" * 64,
    revision=1,
    revision_hash="c" * 64,
)


def test_knowledge_review_allowlist_is_explicit_and_empty_denies() -> None:
    denied = ConfiguredKnowledgeReviewAuthorizer(())
    with pytest.raises(NotFoundError):
        denied.require_capability(
            REVIEWER,
            KnowledgeReviewCapability.REVIEW_CANDIDATE,
            TARGET,
        )

    allowed = ConfiguredKnowledgeReviewAuthorizer((REVIEWER,))
    allowed.require_capability(
        REVIEWER,
        KnowledgeReviewCapability.REVIEW_CANDIDATE,
        TARGET,
    )


def test_policy_approval_has_a_separate_steward_allowlist() -> None:
    policy_authorizer = ConfiguredPolicyStewardAuthorizer((REVIEWER,))
    policy_authorizer.require_capability(
        REVIEWER, PolicyApprovalCapability.APPROVE_REVISION
    )

    with pytest.raises(NotFoundError):
        policy_authorizer.require_capability(
            REVIEWER, PolicyApprovalCapability.SUBMIT_REVISION
        )

    with pytest.raises(NotFoundError):
        ConfiguredPolicyStewardAuthorizer(()).require_capability(
            REVIEWER,
            PolicyApprovalCapability.APPROVE_REVISION,
        )
