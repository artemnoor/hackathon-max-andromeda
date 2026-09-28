from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from andromeda.api.dependencies.auth_session import require_current_account
from andromeda.api.dependencies.composition import get_composition_root
from andromeda.api.dependencies.request_context import get_session
from andromeda.composition import AndromedaContainer
from andromeda.infrastructure.repositories.knowledge_review_auth import (
    ConfiguredKnowledgeReviewAuthorizer,
    ConfiguredPolicyStewardAuthorizer,
)
from andromeda.modules.auth.contracts.public import Account
from andromeda.modules.knowledge.services.review_workflow import KnowledgeReviewWorkflow
from andromeda.modules.policy.services.knowledge_review_adapter import (
    PolicyApprovalReviewAdapter,
)
from andromeda.shared.contracts.errors import NotFoundError

logger = logging.getLogger("andromeda.api.knowledge_review")


def require_knowledge_review_access(
    request: Request,
    account: Annotated[Account, Depends(require_current_account)],
) -> Account:
    settings = request.app.state.settings
    authorized = set(settings.knowledge_reviewer_account_ids) | set(
        settings.policy_steward_account_ids
    )
    if account.account_id not in authorized:
        logger.warning(
            "knowledge_review_route_denied actor_account_id=%s", account.account_id
        )
        raise NotFoundError("Resource was not found")
    return account


def get_knowledge_review_workflow(
    request: Request,
    container: Annotated[AndromedaContainer, Depends(get_composition_root)],
    session: Annotated[Session, Depends(get_session)],
) -> KnowledgeReviewWorkflow:
    settings = request.app.state.settings
    return container.knowledge_review_workflow(
        session,
        authorizer=ConfiguredKnowledgeReviewAuthorizer(
            settings.knowledge_reviewer_account_ids
        ),
        policy_authorizer=ConfiguredPolicyStewardAuthorizer(
            settings.policy_steward_account_ids
        ),
    )


def get_policy_approval_review_adapter(
    request: Request,
    container: Annotated[AndromedaContainer, Depends(get_composition_root)],
    session: Annotated[Session, Depends(get_session)],
) -> PolicyApprovalReviewAdapter:
    settings = request.app.state.settings
    return container.policy_approval_review_adapter(
        session,
        ConfiguredPolicyStewardAuthorizer(settings.policy_steward_account_ids),
    )


__all__ = [
    "get_knowledge_review_workflow",
    "get_policy_approval_review_adapter",
    "require_knowledge_review_access",
]
