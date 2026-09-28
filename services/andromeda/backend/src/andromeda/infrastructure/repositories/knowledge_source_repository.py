"""Persistence adapter for approved source registry revisions and observations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    EvidenceLocator,
    EvidenceRef,
    SourceAllowedRoute,
    SourceId,
    SourceIdentity,
    SourceObservation,
    SourceObservationId,
    SourcePollAttempt,
)
from andromeda.modules.knowledge.domain.sources import (
    is_allowed_source_url,
    observation_id_from_idempotency_key,
    observation_idempotency_key,
)
from andromeda.modules.knowledge.repository.ports import (
    SourceObservationRepository,
    SourcePollAttemptRepository,
    SourceRegistryReader,
    SourceRegistryWriter,
)
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from andromeda.shared.contracts.ids import SourceHash

from ..database.models import (
    IngestRunModel,
    KnowledgeSourceAllowlistModel,
    KnowledgeSourceModel,
    KnowledgeSourceObservationModel,
    KnowledgeSourcePollAttemptModel,
    KnowledgeSourceRegistryRevisionModel,
    SourceSnapshotModel,
)

logger = logging.getLogger("andromeda.infrastructure.repositories.knowledge_source_repository")
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class SqlAlchemyKnowledgeSourceRepository(
    SourceRegistryReader,
    SourceRegistryWriter,
    SourceObservationRepository,
    SourcePollAttemptRepository,
):
    """Append-only persistence adapter; transaction ownership stays with caller."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_source_identity(self, source_id: SourceId) -> SourceIdentity | None:
        row = self._session.get(KnowledgeSourceModel, source_id)
        return _to_source_identity(row) if row is not None else None

    def get_registry_revision(
        self, source_id: SourceId, revision: int
    ) -> ApprovedSourceRegistryRevision | None:
        row = self._session.get(KnowledgeSourceRegistryRevisionModel, (source_id, revision))
        return _to_registry_revision(self._session, row) if row is not None else None

    def get_latest_registry_revision(
        self, source_id: SourceId
    ) -> ApprovedSourceRegistryRevision | None:
        row = self._session.scalar(
            select(KnowledgeSourceRegistryRevisionModel)
            .where(KnowledgeSourceRegistryRevisionModel.source_id == source_id)
            .order_by(KnowledgeSourceRegistryRevisionModel.revision.desc())
            .limit(1)
        )
        return _to_registry_revision(self._session, row) if row is not None else None

    def list_pollable_registry_revisions(self) -> tuple[ApprovedSourceRegistryRevision, ...]:
        revisions = KnowledgeSourceRegistryRevisionModel
        latest_revision = (
            select(
                revisions.source_id.label("source_id"),
                func.max(revisions.revision).label("latest_revision"),
            )
            .group_by(revisions.source_id)
            .subquery()
        )
        rows = self._session.scalars(
            select(revisions)
            .join(
                latest_revision,
                (revisions.source_id == latest_revision.c.source_id)
                & (revisions.revision == latest_revision.c.latest_revision),
            )
            .where(revisions.enabled.is_(True))
            .order_by(revisions.source_id)
            .limit(501)
        ).all()
        if len(rows) > 500:
            raise ValidationError("At most 500 knowledge sources may be enabled for bounded polling")
        return tuple(_to_registry_revision(self._session, row) for row in rows)

    def register_source_identity(self, identity: SourceIdentity) -> SourceIdentity:
        existing = self._session.get(KnowledgeSourceModel, identity.source_id)
        if existing is not None:
            current = _to_source_identity(existing)
            if current != identity:
                raise ConflictError("Source identity is immutable")
            return current

        same_natural_identity = self._session.scalar(
            select(KnowledgeSourceModel).where(
                KnowledgeSourceModel.jurisdiction == identity.jurisdiction.value,
                KnowledgeSourceModel.issuer_id == identity.issuer_id,
                KnowledgeSourceModel.identity_key == identity.identity_key,
            )
        )
        if same_natural_identity is not None:
            raise ConflictError("Source identity key is already registered")

        self._session.add(
            KnowledgeSourceModel(
                source_id=identity.source_id,
                issuer_id=identity.issuer_id,
                jurisdiction=identity.jurisdiction.value,
                identity_key=identity.identity_key,
                display_name=identity.display_name,
                created_at=_utc(identity.created_at),
            )
        )
        self._session.flush()
        return identity

    def append_approved_registry_revision(
        self, revision: ApprovedSourceRegistryRevision
    ) -> ApprovedSourceRegistryRevision:
        if self._session.get(KnowledgeSourceModel, revision.source_id) is None:
            raise NotFoundError("Source identity does not exist")

        current = self.get_registry_revision(revision.source_id, revision.revision)
        if current is not None:
            if current != revision:
                raise ConflictError("Source registry revisions are immutable")
            return current

        latest = self.get_latest_registry_revision(revision.source_id)
        expected_revision = latest.revision + 1 if latest is not None else 1
        if revision.revision != expected_revision:
            raise ConflictError("Source registry revisions must be appended consecutively")

        row = KnowledgeSourceRegistryRevisionModel(
            source_id=revision.source_id,
            revision=revision.revision,
            source_kind=revision.source_kind.value,
            reliability_tier=revision.reliability_tier.value,
            adapter_id=revision.adapter_id,
            adapter_version=revision.adapter_version,
            start_url=str(revision.start_url),
            poll_interval_seconds=revision.poll_interval_seconds,
            freshness_budget_seconds=revision.freshness_budget_seconds,
            enabled=revision.enabled,
            approved_by_account_id=revision.approved_by_account_id,
            approved_at=_utc(revision.approved_at),
            approval_reason=revision.approval_reason,
            recorded_at=_utc(revision.recorded_at),
        )
        self._session.add(row)
        self._session.flush()
        for route in revision.allowlist:
            self._session.add(
                KnowledgeSourceAllowlistModel(
                    source_id=revision.source_id,
                    revision=revision.revision,
                    host=route.host,
                    path_prefix=route.path_prefix,
                )
            )
        self._session.flush()
        return revision

    def record_observation(self, observation: SourceObservation) -> SourceObservation:
        registry = self.get_registry_revision(observation.source_id, observation.registry_revision)
        if registry is None:
            raise NotFoundError("Approved source registry revision does not exist")
        if not all(
            any(
                is_allowed_source_url(
                    str(url), host=route.host, path_prefix=route.path_prefix
                )
                for route in registry.allowlist
            )
            for url in (observation.requested_url, observation.final_url)
        ):
            raise ValidationError("Source observation URL is outside the approved allowlist")

        expected_key = observation_idempotency_key(
            source_id=observation.source_id,
            registry_revision=observation.registry_revision,
            ingest_run_id=observation.ingest_run_id,
            requested_url=str(observation.requested_url),
            snapshot_sha256=observation.snapshot_sha256,
        )
        if observation.idempotency_key != expected_key or observation.source_observation_id != (
            observation_id_from_idempotency_key(expected_key)
        ):
            raise ValidationError("Source observation identity does not match its capture inputs")

        if self._session.get(SourceSnapshotModel, observation.snapshot_sha256) is None:
            raise NotFoundError("Source snapshot does not exist")
        if self._session.get(IngestRunModel, observation.ingest_run_id) is None:
            raise NotFoundError("Ingestion run does not exist")

        existing = self._session.scalar(
            select(KnowledgeSourceObservationModel).where(
                KnowledgeSourceObservationModel.source_id == observation.source_id,
                KnowledgeSourceObservationModel.idempotency_key == observation.idempotency_key,
            )
        )
        if existing is not None:
            stored = _to_observation(existing)
            if stored != observation:
                raise ConflictError("Source observation idempotency key has conflicting metadata")
            return stored

        self._session.add(
            KnowledgeSourceObservationModel(
                source_observation_id=observation.source_observation_id,
                source_id=observation.source_id,
                registry_revision=observation.registry_revision,
                idempotency_key=observation.idempotency_key,
                ingest_run_id=observation.ingest_run_id,
                snapshot_sha256=observation.snapshot_sha256,
                requested_url=str(observation.requested_url),
                final_url=str(observation.final_url),
                status_code=observation.status_code,
                content_type=observation.content_type,
                response_class=observation.response_class,
                access_mode=observation.access_mode,
                truncated=observation.truncated,
                captured_at=_utc(observation.captured_at),
                observed_at=_utc(observation.observed_at),
            )
        )
        self._session.flush()
        logger.info(
            "knowledge_source_observation_recorded source_id=%s observation_id=%s snapshot_hash_prefix=%s",
            observation.source_id,
            observation.source_observation_id,
            observation.snapshot_sha256[:12],
        )
        return observation

    def get_observation(self, observation_id: SourceObservationId) -> SourceObservation | None:
        row = self._session.get(KnowledgeSourceObservationModel, observation_id)
        return _to_observation(row) if row is not None else None

    def resolve_snapshot_evidence(
        self,
        *,
        source_url: HttpUrl,
        snapshot_sha256: SourceHash,
        locator: EvidenceLocator,
    ) -> EvidenceRef | None:
        """Resolve legacy source attribution only to an exact captured observation."""
        logger.debug(
            "knowledge_source_evidence_resolution_started snapshot_hash_prefix=%s",
            snapshot_sha256[:12],
        )
        if (
            source_url.scheme != "https"
            or source_url.username is not None
            or source_url.password is not None
            or source_url.port not in (None, 443)
            or source_url.query is not None
            or source_url.fragment is not None
        ):
            logger.info(
                "knowledge_source_evidence_resolution_rejected_unsafe_url snapshot_hash_prefix=%s",
                snapshot_sha256[:12],
            )
            return None
        url = str(source_url)
        rows = tuple(
            self._session.scalars(
                select(KnowledgeSourceObservationModel)
                .where(
                    KnowledgeSourceObservationModel.snapshot_sha256 == snapshot_sha256,
                    (
                        (KnowledgeSourceObservationModel.requested_url == url)
                        | (KnowledgeSourceObservationModel.final_url == url)
                    ),
                    KnowledgeSourceObservationModel.status_code < 400,
                    KnowledgeSourceObservationModel.truncated.is_(False),
                )
                .order_by(
                    KnowledgeSourceObservationModel.source_id,
                    KnowledgeSourceObservationModel.observed_at,
                    KnowledgeSourceObservationModel.source_observation_id,
                )
                .limit(101)
            ).all()
        )
        if not rows or len(rows) > 100:
            logger.debug(
                "knowledge_source_evidence_resolution_unavailable snapshot_hash_prefix=%s matches=%d",
                snapshot_sha256[:12],
                len(rows),
            )
            return None
        source_ids = {row.source_id for row in rows}
        if len(source_ids) != 1:
            logger.info(
                "knowledge_source_evidence_resolution_ambiguous snapshot_hash_prefix=%s source_count=%d",
                snapshot_sha256[:12],
                len(source_ids),
            )
            return None
        identity = self.get_source_identity(next(iter(source_ids)))
        if identity is None:
            logger.info(
                "knowledge_source_evidence_resolution_missing_identity source_id=%s",
                next(iter(source_ids)),
            )
            return None
        row = rows[0]
        evidence = EvidenceRef(
            source_id=identity.source_id,
            source_observation_id=row.source_observation_id,
            snapshot_sha256=row.snapshot_sha256,
            source_url=source_url,
            locator=locator,
        )
        logger.debug(
            "knowledge_source_evidence_resolution_completed source_id=%s observation_id=%s",
            evidence.source_id,
            evidence.source_observation_id,
        )
        return evidence

    def list_observations(
        self, source_id: SourceId, *, limit: int = 100
    ) -> tuple[SourceObservation, ...]:
        if limit < 1 or limit > 500:
            raise ValidationError("Observation limit must be between 1 and 500")
        rows = self._session.scalars(
            select(KnowledgeSourceObservationModel)
            .where(KnowledgeSourceObservationModel.source_id == source_id)
            .order_by(
                KnowledgeSourceObservationModel.observed_at.desc(),
                KnowledgeSourceObservationModel.source_observation_id,
            )
            .limit(limit)
        ).all()
        return tuple(_to_observation(row) for row in rows)

    def get_latest_attempt(self, source_id: SourceId) -> SourcePollAttempt | None:
        row = self._session.scalar(
            select(KnowledgeSourcePollAttemptModel)
            .where(KnowledgeSourcePollAttemptModel.source_id == source_id)
            .order_by(
                KnowledgeSourcePollAttemptModel.completed_at.desc(),
                KnowledgeSourcePollAttemptModel.attempt_id.desc(),
            )
            .limit(1)
        )
        return _to_poll_attempt(row) if row is not None else None

    def record_attempt(self, attempt: SourcePollAttempt) -> SourcePollAttempt:
        if self.get_registry_revision(attempt.source_id, attempt.registry_revision) is None:
            raise NotFoundError("Source registry revision does not exist for poll attempt")
        existing = self._session.get(KnowledgeSourcePollAttemptModel, attempt.attempt_id)
        if existing is not None:
            stored = _to_poll_attempt(existing)
            if stored != attempt:
                raise ConflictError("Source poll attempt identity has conflicting metadata")
            return stored

        latest = self.get_latest_attempt(attempt.source_id)
        if latest is not None:
            if attempt.started_at < latest.completed_at:
                raise ConflictError("Source poll attempts must be recorded in completion order")
            if attempt.previous_snapshot_sha256 != latest.last_successful_snapshot_sha256:
                raise ConflictError("Source poll attempt was based on a stale successful snapshot")
        if attempt.source_observation_id is not None:
            observation = self.get_observation(attempt.source_observation_id)
            if observation is None:
                raise NotFoundError("Source poll attempt observation does not exist")
            if (
                observation.source_id != attempt.source_id
                or observation.registry_revision != attempt.registry_revision
                or observation.snapshot_sha256 != attempt.snapshot_sha256
            ):
                raise ValidationError("Source poll attempt must match its exact source observation")
        self._session.add(
            KnowledgeSourcePollAttemptModel(
                attempt_id=attempt.attempt_id,
                source_id=attempt.source_id,
                registry_revision=attempt.registry_revision,
                started_at=_utc(attempt.started_at),
                completed_at=_utc(attempt.completed_at),
                outcome=attempt.outcome.value,
                parser_version=attempt.parser_version,
                previous_snapshot_sha256=attempt.previous_snapshot_sha256,
                snapshot_sha256=attempt.snapshot_sha256,
                last_successful_snapshot_sha256=attempt.last_successful_snapshot_sha256,
                source_observation_id=attempt.source_observation_id,
                retry_count=attempt.retry_count,
                next_retry_at=_optional_utc(attempt.next_retry_at),
                failure_code=attempt.failure_code,
                extracted_candidate_count=attempt.extracted_candidate_count,
            )
        )
        self._session.flush()
        logger.info(
            "knowledge_source_poll_attempt_recorded source_id=%s outcome=%s retry_count=%d candidates=%d",
            attempt.source_id,
            attempt.outcome.value,
            attempt.retry_count,
            attempt.extracted_candidate_count,
        )
        return attempt


def _to_source_identity(row: KnowledgeSourceModel) -> SourceIdentity:
    from andromeda.modules.knowledge.contracts.public import SourceJurisdiction

    return SourceIdentity(
        source_id=row.source_id,
        issuer_id=row.issuer_id,
        jurisdiction=SourceJurisdiction(row.jurisdiction),
        identity_key=row.identity_key,
        display_name=row.display_name,
        created_at=_aware(row.created_at),
    )


def _to_registry_revision(
    session: Session, row: KnowledgeSourceRegistryRevisionModel
) -> ApprovedSourceRegistryRevision:
    from andromeda.modules.knowledge.contracts.public import (
        KnowledgeSourceKind,
        SourceReliabilityTier,
    )

    routes = session.scalars(
        select(KnowledgeSourceAllowlistModel)
        .where(
            KnowledgeSourceAllowlistModel.source_id == row.source_id,
            KnowledgeSourceAllowlistModel.revision == row.revision,
        )
        .order_by(KnowledgeSourceAllowlistModel.host, KnowledgeSourceAllowlistModel.path_prefix)
    ).all()
    return ApprovedSourceRegistryRevision(
        source_id=row.source_id,
        revision=row.revision,
        source_kind=KnowledgeSourceKind(row.source_kind),
        reliability_tier=SourceReliabilityTier(row.reliability_tier),
        adapter_id=row.adapter_id,
        adapter_version=row.adapter_version,
        start_url=_HTTP_URL_ADAPTER.validate_python(row.start_url),
        allowlist=tuple(
            SourceAllowedRoute(host=route.host, path_prefix=route.path_prefix)
            for route in routes
        ),
        poll_interval_seconds=row.poll_interval_seconds,
        freshness_budget_seconds=row.freshness_budget_seconds,
        enabled=row.enabled,
        approved_by_account_id=row.approved_by_account_id,
        approved_at=_aware(row.approved_at),
        approval_reason=row.approval_reason,
        recorded_at=_aware(row.recorded_at),
    )


def _to_observation(row: KnowledgeSourceObservationModel) -> SourceObservation:
    return SourceObservation(
        source_observation_id=row.source_observation_id,
        source_id=row.source_id,
        registry_revision=row.registry_revision,
        idempotency_key=row.idempotency_key,
        ingest_run_id=row.ingest_run_id,
        snapshot_sha256=row.snapshot_sha256,
        requested_url=_HTTP_URL_ADAPTER.validate_python(row.requested_url),
        final_url=_HTTP_URL_ADAPTER.validate_python(row.final_url),
        status_code=row.status_code,
        content_type=row.content_type,
        response_class=row.response_class,
        access_mode=row.access_mode,
        truncated=row.truncated,
        captured_at=_aware(row.captured_at),
        observed_at=_aware(row.observed_at),
    )


def _to_poll_attempt(row: KnowledgeSourcePollAttemptModel) -> SourcePollAttempt:
    from andromeda.modules.knowledge.contracts.public import SourcePollOutcome

    return SourcePollAttempt(
        attempt_id=row.attempt_id,
        source_id=row.source_id,
        registry_revision=row.registry_revision,
        started_at=_aware(row.started_at),
        completed_at=_aware(row.completed_at),
        outcome=SourcePollOutcome(row.outcome),
        parser_version=row.parser_version,
        previous_snapshot_sha256=row.previous_snapshot_sha256,
        snapshot_sha256=row.snapshot_sha256,
        last_successful_snapshot_sha256=row.last_successful_snapshot_sha256,
        source_observation_id=row.source_observation_id,
        retry_count=row.retry_count,
        next_retry_at=_optional_aware(row.next_retry_at),
        failure_code=row.failure_code,
        extracted_candidate_count=row.extracted_candidate_count,
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _optional_aware(value: datetime | None) -> datetime | None:
    return _aware(value) if value is not None else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None


__all__ = ["SqlAlchemyKnowledgeSourceRepository"]
