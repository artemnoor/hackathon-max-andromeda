"""Shared validation of knowledge evidence against captured allow-listed observations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    KnowledgeSourceAllowlistModel,
    KnowledgeSourceObservationModel,
    KnowledgeSourceRegistryRevisionModel,
)
from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.modules.knowledge.domain.sources import is_allowed_source_url
from andromeda.shared.contracts.errors import NotFoundError, ValidationError


def validate_knowledge_evidence(
    session: Session,
    evidence: tuple[EvidenceRef, ...],
    *,
    recorded_at: datetime,
    required_source_observation_id: str | None = None,
) -> None:
    for reference in evidence:
        observation = session.get(
            KnowledgeSourceObservationModel, reference.source_observation_id
        )
        if observation is None:
            raise NotFoundError("Knowledge evidence observation does not exist")
        if (
            observation.source_id != reference.source_id
            or observation.snapshot_sha256 != reference.snapshot_sha256
        ):
            raise ValidationError("Knowledge evidence does not match its captured observation")
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValidationError("Knowledge evidence recorded_at must be timezone-aware")
        record_time = recorded_at.astimezone(UTC)
        observed_at = _aware(observation.observed_at)
        if (
            required_source_observation_id == reference.source_observation_id
            and record_time < observed_at
        ):
            raise ValidationError("claim revision cannot predate its source observation")
        if record_time < observed_at:
            raise ValidationError("candidate cannot predate its evidence observation")
        registry = session.get(
            KnowledgeSourceRegistryRevisionModel,
            (observation.source_id, observation.registry_revision),
        )
        if registry is None:
            raise NotFoundError("Knowledge evidence registry revision does not exist")
        routes = session.scalars(
            select(KnowledgeSourceAllowlistModel).where(
                KnowledgeSourceAllowlistModel.source_id == observation.source_id,
                KnowledgeSourceAllowlistModel.revision == observation.registry_revision,
            )
        ).all()
        if not any(
            is_allowed_source_url(
                str(reference.source_url), host=route.host, path_prefix=route.path_prefix
            )
            for route in routes
        ):
            raise ValidationError("Knowledge evidence URL is outside its approved source allowlist")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["validate_knowledge_evidence"]
