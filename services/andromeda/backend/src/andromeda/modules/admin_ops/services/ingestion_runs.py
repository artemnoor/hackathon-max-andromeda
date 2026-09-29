from __future__ import annotations

import logging

from andromeda.shared.contracts.errors import ContractError, ErrorCode, NotFoundError
from andromeda.shared.contracts.ids import IngestRunId

from ..contracts.public import IngestionRetryRequest, IngestionRunFilters
from ..contracts.results import IngestionRetryResult, IngestionRunDetailResult, IngestionRunListResult
from ..repository.ports import IngestionRetryExecutor, IngestionRunReader, IngestionRunRecovery


logger = logging.getLogger("andromeda.admin_ops")


class IngestionRunService:
    """Application service for bounded ingestion audit views and retry commands."""

    def __init__(
        self,
        reader: IngestionRunReader,
        executor: IngestionRetryExecutor | None = None,
        recovery: IngestionRunRecovery | None = None,
        stale_timeout_seconds: int = 30 * 60,
    ) -> None:
        self._reader = reader
        self._executor = executor
        self._recovery = recovery
        self._stale_timeout_seconds = stale_timeout_seconds

    def list(self, filters: IngestionRunFilters) -> IngestionRunListResult:
        logger.debug("ingestion_runs_use_case_start status=%s limit=%d", filters.status, filters.limit)
        result = self._reader.list(filters)
        logger.info("ingestion_runs_use_case_complete result_count=%d total=%d", len(result.items), result.total)
        return result

    def get(self, run_id: IngestRunId) -> IngestionRunDetailResult:
        logger.debug("ingestion_run_detail_use_case_start run_id=%s", run_id)
        result = self._reader.get(run_id)
        if result is None:
            logger.warning("ingestion_run_detail_not_found run_id=%s", run_id)
            raise NotFoundError("Ingestion run was not found")
        logger.info("ingestion_run_detail_use_case_complete run_id=%s", run_id)
        return result

    def retry(self, request: IngestionRetryRequest) -> IngestionRetryResult:
        if self._executor is None:
            raise NotFoundError("Resource was not found")
        if self._recovery is not None:
            recovered = self._recovery.recover_stale(timeout_seconds=self._stale_timeout_seconds)
            if recovered:
                logger.warning("ingestion_stale_runs_recovered count=%d run_ids=%s", len(recovered), ",".join(recovered))
        logger.info(
            "ingestion_retry_requested operator=ops_api_key source_profile=%s retry_of=%s",
            request.profile.profile_id,
            request.retry_of_run_id or "latest-profile-run",
        )
        outcome = self._executor.execute(request)
        result = self._reader.get(outcome.run_id)
        if result is None:
            logger.error("ingestion_retry_audit_missing run_id=%s", outcome.run_id)
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Ingestion retry audit was not persisted")
        return IngestionRetryResult(run=result.run)


__all__ = ["IngestionRunService"]
