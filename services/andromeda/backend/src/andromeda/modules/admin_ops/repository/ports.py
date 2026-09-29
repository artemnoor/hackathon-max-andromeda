from __future__ import annotations

from typing import Protocol

from andromeda.shared.contracts.ids import IngestRunId

from ..contracts.public import IngestionRetryRequest, IngestionRunFilters
from ..contracts.results import IngestionRetryOutcome, IngestionRunDetailResult, IngestionRunListResult


class IngestionRunReader(Protocol):
    def list(self, filters: IngestionRunFilters) -> IngestionRunListResult: ...

    def get(self, run_id: IngestRunId) -> IngestionRunDetailResult | None: ...


class IngestionRetryExecutor(Protocol):
    def execute(self, request: IngestionRetryRequest) -> IngestionRetryOutcome: ...


class IngestionRunRecovery(Protocol):
    def recover_stale(self, *, timeout_seconds: int) -> tuple[IngestRunId, ...]: ...


__all__ = ["IngestionRetryExecutor", "IngestionRunReader", "IngestionRunRecovery"]
