from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from andromeda.api.dependencies.auth_session import require_current_account
from andromeda.api.dependencies.composition import get_composition_root
from andromeda.api.dependencies.request_context import get_session
from andromeda.composition import AndromedaContainer
from andromeda.modules.auth.contracts.public import Account
from andromeda.modules.knowledge.services.manual_source_commands import (
    ManualSourceCommands,
)
from andromeda.shared.contracts.errors import NotFoundError

logger = logging.getLogger("andromeda.api.knowledge_manual")


def require_knowledge_source_steward(
    request: Request,
    account: Annotated[Account, Depends(require_current_account)],
) -> Account:
    configured = request.app.state.settings.knowledge_source_steward_account_ids
    if account.account_id not in configured:
        logger.warning(
            "knowledge_source_steward_route_denied actor_account_id=%s",
            account.account_id,
        )
        raise NotFoundError("Resource was not found")
    return account


def get_knowledge_manual_commands(
    container: Annotated[AndromedaContainer, Depends(get_composition_root)],
    session: Annotated[Session, Depends(get_session)],
) -> ManualSourceCommands:
    return container.knowledge_manual_commands(session)


__all__ = ["get_knowledge_manual_commands", "require_knowledge_source_steward"]
