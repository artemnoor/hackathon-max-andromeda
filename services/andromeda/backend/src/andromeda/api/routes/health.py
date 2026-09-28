"""Process and database readiness probes for deploys and orchestrators."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text


router = APIRouter(tags=["health"])
logger = logging.getLogger("andromeda.api.health")


@router.get("/health/live", include_in_schema=True)
def live() -> dict[str, str]:
    return {"status": "live"}


def expected_schema_revision() -> str:
    configured_location = os.environ.get("ANDROMEDA_ALEMBIC_SCRIPT_LOCATION")
    module_path = Path(__file__).resolve()
    candidates = [
        Path(configured_location) if configured_location else None,
        Path.cwd() / "alembic",
        module_path.parents[4] / "alembic",
        module_path.parents[3] / "alembic",
    ]
    for candidate in candidates:
        if candidate is None or not candidate.is_dir():
            continue
        config = Config()
        config.set_main_option("script_location", str(candidate))
        heads = ScriptDirectory.from_config(config).get_heads()
        if len(heads) != 1:
            raise RuntimeError("Alembic must have exactly one migration head")
        return heads[0]
    raise RuntimeError("Alembic script location is unavailable")


@router.get("/health/ready", include_in_schema=True, response_model=None)
def ready(request: Request) -> JSONResponse | dict[str, str]:
    expected = getattr(request.app.state, "expected_schema_revision", None)
    if not isinstance(expected, str) or not expected:
        logger.error("health_ready_failed reason=schema_metadata_unavailable")
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "schema_metadata_unavailable"})
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revisions = tuple(connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all())
    except Exception:
        logger.warning("health_ready_failed reason=database_unavailable")
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "database_unavailable"})
    if revisions != (expected,):
        actual = str(revisions[0]) if revisions else "missing"
        logger.warning("health_ready_failed reason=schema_mismatch actual=%s expected=%s", actual, expected)
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "schema_mismatch", "schema": actual, "expectedSchema": expected},
        )
    return {"status": "ready", "schema": expected, "expectedSchema": expected, "database": "ok"}


__all__ = ["expected_schema_revision", "router"]
