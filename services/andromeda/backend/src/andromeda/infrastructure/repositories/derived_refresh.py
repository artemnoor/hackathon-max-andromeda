"""Post-commit adapter for semantic and program projection refreshes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter

from andromeda.modules.analytics.services.projection_builder import ProgramProjectionService
from andromeda.modules.program_analytics.contracts.public import (
    DerivedRefreshOutcome,
    DerivedRefreshPort,
    DerivedRefreshRequest,
    DerivedRefreshStatus,
)
from andromeda.modules.semantic.services.enrichment import SemanticEnrichmentService

logger = logging.getLogger("andromeda.infrastructure.repositories.derived_refresh")


class SqlAlchemyDerivedRefreshAdapter(DerivedRefreshPort):
    """Compose existing derived services behind one post-commit port."""

    def __init__(
        self,
        semantic_enrichment: SemanticEnrichmentService,
        projection_service: ProgramProjectionService,
    ) -> None:
        self._semantic_enrichment = semantic_enrichment
        self._projection_service = projection_service

    def refresh(self, request: DerivedRefreshRequest) -> DerivedRefreshOutcome:
        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        input_hash = _input_hash(request)
        logger.info(
            "derived_refresh_started ingest_run_id=%s university_id=%s affected_programs=%d semantic_version=%s classifier_version=%s projection_version=%s",
            request.ingest_run_id,
            request.university_id,
            len(request.affected_program_ids),
            request.semantic_version,
            request.classifier_version,
            request.projection_version,
        )
        try:
            semantic_run = self._semantic_enrichment.enrich(
                university_id=request.university_id,
                ingest_run_id=request.ingest_run_id,
                curricula=request.curricula,
                disciplines=request.disciplines,
            )
            projections = self._projection_service.refresh(request, semantic_run)
            outcome = DerivedRefreshOutcome(
                ingest_run_id=request.ingest_run_id,
                university_id=request.university_id,
                status=DerivedRefreshStatus.COMPLETED,
                affected_program_count=len(request.affected_program_ids),
                refreshed_program_count=len(projections),
                semantic_run_id=semantic_run.id,
                input_hash=input_hash,
                semantic_version=request.semantic_version,
                classifier_version=request.classifier_version,
                projection_version=request.projection_version,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            logger.info(
                "derived_refresh_completed ingest_run_id=%s semantic_run_id=%s refreshed_programs=%d duration_ms=%d",
                request.ingest_run_id,
                semantic_run.id,
                len(projections),
                int((perf_counter() - started_clock) * 1000),
            )
            return outcome
        except Exception as exc:
            logger.exception(
                "derived_refresh_failed ingest_run_id=%s error_code=%s duration_ms=%d",
                request.ingest_run_id,
                type(exc).__name__,
                int((perf_counter() - started_clock) * 1000),
            )
            raise


def _input_hash(request: DerivedRefreshRequest) -> str:
    payload = "|".join(
        (
            request.ingest_run_id,
            request.university_id,
            request.semantic_version,
            request.classifier_version,
            request.projection_version,
            *sorted(str(value) for value in request.affected_program_ids),
            *sorted(request.source_hashes),
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["SqlAlchemyDerivedRefreshAdapter"]
