from __future__ import annotations

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import IngestRunId

from ..domain.entities import IngestionRunDetail, IngestionRunSummary
from ..contracts.public import IngestionRetryProfile, IngestionRetrySource


class IngestionRunListResult(ContractModel):
    items: tuple[IngestionRunSummary, ...] = ()
    total: int = Field(strict=True, ge=0)


class IngestionRunDetailResult(ContractModel):
    run: IngestionRunDetail


class IngestionRetryOutcome(ContractModel):
    run_id: IngestRunId
    source: IngestionRetrySource
    profile: IngestionRetryProfile


class IngestionRetryResult(ContractModel):
    run: IngestionRunDetail


__all__ = ["IngestionRetryOutcome", "IngestionRetryResult", "IngestionRunDetailResult", "IngestionRunListResult"]
