from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator


logger = logging.getLogger("andromeda.contracts.validation")


class ContractModel(BaseModel):
    """Strict base for every cross-module runtime-validated contract."""

    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)

    @model_validator(mode="wrap")
    @classmethod
    def log_validation(cls, values: Any, handler: Any) -> Any:
        logger.debug("contract_boundary model=%s", cls.__name__)
        try:
            result = handler(values)
        except ValidationError as exc:
            paths = tuple(".".join(str(part) for part in error.get("loc", ())) for error in exc.errors())
            logger.warning("contract_rejected model=%s paths=%s", cls.__name__, paths)
            raise
        return result
