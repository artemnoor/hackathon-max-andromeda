from __future__ import annotations

import logging
import secrets

from fastapi import Header, Request

from andromeda.shared.contracts.errors import NotFoundError


logger = logging.getLogger("andromeda.api.admin_ops")


def require_ops_access(
    request: Request,
    ops_key: str | None = Header(default=None, alias="X-Andromeda-Ops-Key"),
) -> None:
    configured_key = request.app.state.settings.ops_api_key
    if configured_key is None or ops_key is None or not secrets.compare_digest(configured_key, ops_key):
        logger.warning("admin_ops_access_denied")
        raise NotFoundError("Resource was not found")


__all__ = ["require_ops_access"]
