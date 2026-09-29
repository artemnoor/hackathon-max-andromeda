from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from pydantic import HttpUrl, TypeAdapter
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.infrastructure.repositories.knowledge_source_repository import (
    SqlAlchemyKnowledgeSourceRepository,
)
from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    SourceObservation,
)
from andromeda.modules.knowledge.domain.sources import (
    is_allowed_source_url,
    observation_id_from_idempotency_key,
    observation_idempotency_key,
)
from andromeda.modules.knowledge.repository.ports import KnowledgeManualSnapshotCapture
from andromeda.shared.contracts.errors import ConflictError, ValidationError

logger = logging.getLogger("andromeda.infrastructure.knowledge_manual_capture")
_HTTP_URL = TypeAdapter(HttpUrl)


class SqlAlchemyKnowledgeManualSnapshotCapture(KnowledgeManualSnapshotCapture):
    """Persist a human upload through the existing capture-only ingestion seam."""

    def __init__(self, engine: Engine, session: Session) -> None:
        self._engine = engine
        self._session = session

    def capture(
        self,
        *,
        actor_account_id: str,
        registry: ApprovedSourceRegistryRevision,
        requested_url: str,
        content_type: str,
        body: bytes,
        idempotency_key: str,
        captured_at: datetime,
    ) -> SourceObservation:
        logger.debug(
            "knowledge_manual_capture_start source_id=%s registry_revision=%d body_bytes=%d",
            registry.source_id,
            registry.revision,
            len(body),
        )
        if not any(
            is_allowed_source_url(requested_url, host=route.host, path_prefix=route.path_prefix)
            for route in registry.allowlist
        ):
            raise ValidationError("Manual document URL is outside the approved source allowlist")
        content_hash = hashlib.sha256(body).hexdigest()
        key_digest = hashlib.sha256(
            f"{actor_account_id}\0{idempotency_key}".encode()
        ).hexdigest()
        run_id = f"ingest:{key_digest[:32]}"
        observation_key = observation_idempotency_key(
            source_id=registry.source_id,
            registry_revision=registry.revision,
            ingest_run_id=run_id,
            requested_url=requested_url,
            snapshot_sha256=content_hash,
        )
        observation_id = observation_id_from_idempotency_key(observation_key)
        repository = SqlAlchemyKnowledgeSourceRepository(self._session)
        existing = repository.get_observation(observation_id)
        if existing is not None:
            if (
                existing.source_id != registry.source_id
                or existing.registry_revision != registry.revision
                or existing.snapshot_sha256 != content_hash
                or str(existing.requested_url) != requested_url
                or existing.access_mode != "operator_upload"
            ):
                raise ConflictError("Manual snapshot idempotency identity conflicts with stored capture")
            return existing

        writer = SqlAlchemyIngestionRepository(self._engine)
        run_id = writer.start_run(
            run_id=run_id,
            source_profile="knowledge_manual:" + hashlib.sha256(
                registry.source_id.encode("utf-8")
            ).hexdigest()[:16],
            source_revision=f"registry:{registry.revision}",
            configuration_version="manual-upload.v1",
            university_id="university:legacy",
            projection_target="knowledge_capture",
            idempotency_key=key_digest,
        )
        snapshot = RawSourceSnapshot(
            source_kind="knowledge_manual_document",
            requested_url=_HTTP_URL.validate_python(requested_url),
            final_url=_HTTP_URL.validate_python(requested_url),
            status_code=200,
            content_type=content_type,
            captured_at=captured_at,
            content_sha256=content_hash,
            body=body,
            response_class="manual_upload",
            access_mode="operator_upload",
            truncated=False,
        )
        try:
            writer.record_staged_source_snapshots(run_id, (snapshot,))
            observation = SourceObservation(
                source_observation_id=observation_id,
                source_id=registry.source_id,
                registry_revision=registry.revision,
                idempotency_key=observation_key,
                ingest_run_id=run_id,
                snapshot_sha256=content_hash,
                requested_url=_HTTP_URL.validate_python(requested_url),
                final_url=_HTTP_URL.validate_python(requested_url),
                status_code=200,
                content_type=content_type,
                response_class="manual_upload",
                access_mode="operator_upload",
                truncated=False,
                captured_at=captured_at,
                observed_at=datetime.now(UTC),
            )
            repository.record_observation(observation)
            self._session.commit()
            writer.finish_source_capture_run(run_id)
            logger.info(
                "knowledge_manual_capture_complete source_id=%s observation_id=%s snapshot_hash_prefix=%s",
                registry.source_id,
                observation.source_observation_id,
                content_hash[:12],
            )
            return observation
        except Exception as exc:
            self._session.rollback()
            try:
                writer.mark_failed(run_id, RuntimeError("manual_snapshot_capture_failed"))
            except Exception as mark_failed_error:  # noqa: BLE001 - preserve the original capture failure.
                logger.warning(
                    "knowledge_manual_capture_failure_mark_failed_failed run_id=%s error_type=%s",
                    run_id,
                    type(mark_failed_error).__name__,
                )
            logger.error(
                "knowledge_manual_capture_failed source_id=%s run_id=%s error_type=%s",
                registry.source_id,
                run_id,
                type(exc).__name__,
            )
            raise


__all__ = ["SqlAlchemyKnowledgeManualSnapshotCapture"]
