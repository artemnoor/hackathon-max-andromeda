from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from andromeda.ingestion.quality import evaluate_quality
from andromeda.ingestion.capabilities import CapabilityPreflightError, preflight
from andromeda.ingestion.registry import create_adapter
from andromeda.modules.admin_ops.contracts.public import IngestionRetryRequest
from andromeda.modules.admin_ops.contracts.results import IngestionRetryOutcome
from andromeda.shared.contracts.errors import ContractError, ErrorCode

from .ingestion import SqlAlchemyIngestionRepository


logger = logging.getLogger("andromeda.infrastructure.repositories.ingestion_retry")


class SqlAlchemyIngestionRetryExecutor:
    """Execute only registry-owned, allowlisted ingestion profiles."""

    def __init__(self, engine: Any, environment: str, *, max_attempts: int = 2, backoff_seconds: float = 0.25) -> None:
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if backoff_seconds < 0 or backoff_seconds > 5:
            raise ValueError("backoff_seconds must be between 0 and 5")
        self._engine = engine
        self._environment = environment
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds

    def execute(self, request: IngestionRetryRequest) -> IngestionRetryOutcome:
        profile = request.profile
        if profile.mode == "live" and self._environment != "staging":
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Live ingestion is available only in staging")

        repository = SqlAlchemyIngestionRepository(self._engine)
        existing_id = repository.find_run_by_idempotency_key(request.idempotency_key)
        if existing_id is not None:
            logger.info("admin_ops_retry_idempotent_hit run_id=%s profile=%s", existing_id, profile.profile_id)
            return IngestionRetryOutcome(run_id=existing_id, source=request.source, profile=profile)

        run_id = f"ingest:{uuid4().hex}"
        retry_of_run_id = request.retry_of_run_id or repository.latest_run_id(profile.profile_id)
        resolved_run_id = repository.start_run(
            run_id,
            source_profile=profile.profile_id,
            source_revision=profile.source_revision,
            configuration_version=profile.configuration_version,
            retry_of_run_id=retry_of_run_id,
            idempotency_key=request.idempotency_key,
            university_id=f"university:{profile.university}",
        )
        if resolved_run_id != run_id:
            logger.info("admin_ops_retry_idempotent_race run_id=%s profile=%s", resolved_run_id, profile.profile_id)
            return IngestionRetryOutcome(run_id=resolved_run_id, source=request.source, profile=profile)

        try:
            preflight(profile.university)
        except CapabilityPreflightError as exc:
            repository.mark_failed(run_id, ContractError(ErrorCode.CONTRACT_ERROR, str(exc)))
            return IngestionRetryOutcome(run_id=run_id, source=request.source, profile=profile)

        adapter = create_adapter(profile.university)
        try:
            for attempt in range(1, self._max_attempts + 1):
                try:
                    captured = adapter.capture(mode=profile.mode)
                    repository.record_captured_metadata(run_id, captured)
                    raw, canonical = adapter.parse(captured)
                    repository.record_source_metadata(run_id, raw)
                    previous = repository.previous_projection(str(canonical.university.id))
                    quality = evaluate_quality(raw, canonical, previous=previous, run_id=run_id)
                    repository.record_quality(
                        run_id,
                        quality,
                        university_id=str(canonical.university.id),
                        program_ids=tuple(str(program.id) for program in canonical.programs),
                    )
                    if not quality.accepted:
                        raise ContractError(
                            ErrorCode.CONTRACT_ERROR,
                            "INGESTION_QUALITY_REJECTED: " + ",".join(quality.blocking_reasons),
                        )
                    repository.ingest(raw, canonical, run_id=run_id)
                    logger.info(
                        "admin_ops_retry_attempt_succeeded run_id=%s profile=%s attempt=%d quality=%s",
                        run_id,
                        profile.profile_id,
                        attempt,
                        quality.status,
                    )
                    return IngestionRetryOutcome(run_id=run_id, source=request.source, profile=profile)
                except Exception as exc:
                    if attempt < self._max_attempts and _retryable(exc):
                        delay = min(self._backoff_seconds * (2 ** (attempt - 1)), 2.0)
                        logger.warning(
                            "admin_ops_retry_attempt_retrying run_id=%s profile=%s attempt=%d delay_seconds=%.3f error_type=%s",
                            run_id,
                            profile.profile_id,
                            attempt,
                            delay,
                            type(exc).__name__,
                        )
                        if delay:
                            time.sleep(delay)
                        continue
                    repository.mark_failed(run_id, exc)
                    logger.warning(
                        "admin_ops_retry_failed run_id=%s profile=%s attempts=%d error_code=%s",
                        run_id,
                        profile.profile_id,
                        attempt,
                        type(exc).__name__,
                    )
                    return IngestionRetryOutcome(run_id=run_id, source=request.source, profile=profile)
        finally:
            close = getattr(adapter, "close", None)
            if close is not None:
                close()
        raise AssertionError("ingestion retry executor left without a terminal outcome")


def _retryable(error: Exception) -> bool:
    return isinstance(error, (TimeoutError, ConnectionError, OSError))


__all__ = ["SqlAlchemyIngestionRetryExecutor"]
