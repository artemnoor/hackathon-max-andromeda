"""PostgreSQL persistence for exact, provenance-bearing claim relations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    KnowledgeClaimModel,
    KnowledgeClaimRelationEvidenceModel,
    KnowledgeClaimRelationModel,
)
from andromeda.infrastructure.repositories.knowledge_evidence import (
    validate_knowledge_evidence,
)
from andromeda.modules.knowledge.contracts.public import (
    ClaimRevisionRef,
    EvidenceLocator,
    EvidenceRef,
    KnowledgeClaimRelationRevision,
    KnowledgeRelationId,
    KnowledgeRelationKind,
    KnowledgeRelationReviewState,
    TemporalInterval,
)
from andromeda.modules.knowledge.repository.ports import KnowledgeRelationRepository
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger("andromeda.infrastructure.repositories.knowledge_relations")
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class SqlAlchemyKnowledgeRelationRepository(KnowledgeRelationRepository):
    """Stores immutable relation revisions; proposed edges never count as canonical."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append_relation(
        self, relation: KnowledgeClaimRelationRevision
    ) -> KnowledgeClaimRelationRevision:
        existing = self.get_relation(relation.relation_id, relation.revision)
        if existing is not None:
            if existing != relation:
                raise ConflictError("Knowledge relation revisions are immutable")
            return existing
        latest = self._session.scalar(
            select(KnowledgeClaimRelationModel)
            .where(KnowledgeClaimRelationModel.relation_id == relation.relation_id)
            .order_by(KnowledgeClaimRelationModel.revision.desc())
            .limit(1)
        )
        expected_revision = latest.revision + 1 if latest is not None else 1
        if relation.revision != expected_revision:
            raise ConflictError("Knowledge relation revisions must be appended consecutively")
        if latest is not None and _aware(latest.recorded_at) >= relation.recorded_at:
            raise ValidationError("Knowledge relation recorded_at must increase by revision")
        if relation.review_state not in {
            KnowledgeRelationReviewState.CANDIDATE,
            KnowledgeRelationReviewState.UNRESOLVED,
        }:
            raise ValidationError("Relation approval/rejection requires the review event capability")
        source_claim = self._validate_endpoint(relation.source, recorded_at=relation.recorded_at)
        target_claim = self._validate_endpoint(relation.target, recorded_at=relation.recorded_at)
        if relation.valid_time is not None:
            _validate_interval_intersection(
                relation.valid_time,
                (
                    (
                        _aware(source_claim.valid_start) if source_claim.valid_start else None,
                        _aware(source_claim.valid_end) if source_claim.valid_end else None,
                    ),
                    (
                        _aware(target_claim.valid_start) if target_claim.valid_start else None,
                        _aware(target_claim.valid_end) if target_claim.valid_end else None,
                    ),
                ),
            )
        validate_knowledge_evidence(
            self._session,
            relation.evidence,
            recorded_at=relation.recorded_at,
        )
        if relation.kind is KnowledgeRelationKind.DERIVED_FROM:
            self._validate_no_derived_from_cycle(relation)

        interval = relation.valid_time
        row = KnowledgeClaimRelationModel(
            relation_id=relation.relation_id,
            revision=relation.revision,
            content_hash=relation.content_hash,
            relation_kind=relation.kind.value,
            source_claim_id=relation.source.claim_id,
            source_claim_revision=relation.source.revision,
            target_claim_id=relation.target.claim_id,
            target_claim_revision=relation.target.revision,
            valid_start=interval.start if interval else None,
            valid_end=interval.end if interval else None,
            review_state=relation.review_state.value,
            recorded_at=relation.recorded_at,
        )
        self._session.add(row)
        self._session.flush()
        evidence_rows = [
            KnowledgeClaimRelationEvidenceModel(
                relation_id=relation.relation_id,
                relation_revision=relation.revision,
                ordinal=ordinal,
                source_observation_id=item.source_observation_id,
                snapshot_sha256=item.snapshot_sha256,
                source_url=str(item.source_url),
                locator_page=item.locator.page,
                locator_table=item.locator.table,
                locator_row=item.locator.row,
                locator_section=item.locator.section,
                locator_field=item.locator.field,
                locator_record_key=item.locator.record_key,
                inferred=item.inferred,
            )
            for ordinal, item in enumerate(relation.evidence)
        ]
        self._session.add_all(evidence_rows)
        self._session.flush()
        logger.info(
            "knowledge_relation_revision_appended relation_id=%s revision=%d kind=%s review_state=%s",
            relation.relation_id,
            relation.revision,
            relation.kind.value,
            relation.review_state.value,
        )
        return relation

    def get_relation(
        self, relation_id: KnowledgeRelationId, revision: int
    ) -> KnowledgeClaimRelationRevision | None:
        row = self._session.get(KnowledgeClaimRelationModel, (relation_id, revision))
        return self._to_contract(row) if row is not None else None

    def list_relations(
        self,
        claim_id: str,
        *,
        kinds: tuple[KnowledgeRelationKind, ...] = (),
        include_incoming: bool = True,
        approved_only: bool = True,
        limit: int = 1000,
    ) -> tuple[KnowledgeClaimRelationRevision, ...]:
        if not 1 <= limit <= 1000:
            raise ValidationError("Knowledge relation traversal limit must be between 1 and 1000")
        latest_revisions = (
            select(
                KnowledgeClaimRelationModel.relation_id.label("relation_id"),
                func.max(KnowledgeClaimRelationModel.revision).label("revision"),
            )
            .group_by(KnowledgeClaimRelationModel.relation_id)
            .subquery()
        )
        endpoint_filter = KnowledgeClaimRelationModel.source_claim_id == claim_id
        if include_incoming:
            endpoint_filter = endpoint_filter | (KnowledgeClaimRelationModel.target_claim_id == claim_id)
        query = (
            select(KnowledgeClaimRelationModel)
            .join(
                latest_revisions,
                (KnowledgeClaimRelationModel.relation_id == latest_revisions.c.relation_id)
                & (KnowledgeClaimRelationModel.revision == latest_revisions.c.revision),
            )
            .where(endpoint_filter)
            .order_by(KnowledgeClaimRelationModel.relation_id)
            .limit(limit + 1)
        )
        if kinds:
            query = query.where(
                KnowledgeClaimRelationModel.relation_kind.in_(tuple(item.value for item in kinds))
            )
        if approved_only:
            query = query.where(
                KnowledgeClaimRelationModel.review_state == KnowledgeRelationReviewState.APPROVED.value
            )
        rows = self._session.scalars(query).all()
        if len(rows) > limit:
            raise ValidationError("Knowledge relation traversal exceeds its explicit node limit")
        return tuple(self._to_contract(row) for row in rows)

    def _validate_endpoint(
        self, reference: ClaimRevisionRef, *, recorded_at: datetime
    ) -> KnowledgeClaimModel:
        row = self._session.get(KnowledgeClaimModel, (reference.claim_id, reference.revision))
        if row is None:
            raise NotFoundError("Knowledge relation endpoint claim revision does not exist")
        if _aware(row.recorded_at) > recorded_at:
            raise ValidationError("Knowledge relation cannot predate an endpoint claim revision")
        return row

    def _validate_no_derived_from_cycle(self, relation: KnowledgeClaimRelationRevision) -> None:
        pending = [relation.target.claim_id]
        visited: set[str] = set()
        adjacency: dict[str, set[str]] = {}
        rows = self._session.scalars(
            select(KnowledgeClaimRelationModel).where(
                KnowledgeClaimRelationModel.relation_kind == KnowledgeRelationKind.DERIVED_FROM.value,
                KnowledgeClaimRelationModel.review_state != KnowledgeRelationReviewState.REJECTED.value,
            )
        ).all()
        latest: dict[str, KnowledgeClaimRelationModel] = {}
        for item in rows:
            previous = latest.get(item.relation_id)
            if previous is None or item.revision > previous.revision:
                latest[item.relation_id] = item
        for item in latest.values():
            adjacency.setdefault(item.source_claim_id, set()).add(item.target_claim_id)
        adjacency.setdefault(relation.source.claim_id, set()).add(relation.target.claim_id)
        traversed = 0
        while pending:
            node = pending.pop()
            if node == relation.source.claim_id:
                raise ValidationError("DERIVED_FROM relation would create a directed cycle")
            if node in visited:
                continue
            visited.add(node)
            traversed += 1
            if traversed > 1000:
                raise ValidationError("DERIVED_FROM cycle check exceeds the 1000-node limit")
            pending.extend(sorted(adjacency.get(node, ()), reverse=True))

    def _to_contract(self, row: KnowledgeClaimRelationModel) -> KnowledgeClaimRelationRevision:
        evidence_rows = self._session.scalars(
            select(KnowledgeClaimRelationEvidenceModel)
            .where(
                KnowledgeClaimRelationEvidenceModel.relation_id == row.relation_id,
                KnowledgeClaimRelationEvidenceModel.relation_revision == row.revision,
            )
            .order_by(KnowledgeClaimRelationEvidenceModel.ordinal)
        ).all()
        interval = (
            TemporalInterval(
                start=_aware(row.valid_start) if row.valid_start else None,
                end=_aware(row.valid_end) if row.valid_end else None,
            )
            if row.valid_start is not None or row.valid_end is not None
            else None
        )
        return KnowledgeClaimRelationRevision(
            relation_id=row.relation_id,
            revision=row.revision,
            content_hash=row.content_hash,
            kind=KnowledgeRelationKind(row.relation_kind),
            source=ClaimRevisionRef(claim_id=row.source_claim_id, revision=row.source_claim_revision),
            target=ClaimRevisionRef(claim_id=row.target_claim_id, revision=row.target_claim_revision),
            valid_time=interval,
            review_state=KnowledgeRelationReviewState(row.review_state),
            evidence=tuple(
                EvidenceRef(
                    source_id=source_id_for_observation(self._session, item.source_observation_id),
                    source_observation_id=item.source_observation_id,
                    snapshot_sha256=item.snapshot_sha256,
                    source_url=_HTTP_URL_ADAPTER.validate_python(item.source_url),
                    locator=EvidenceLocator(
                        page=item.locator_page,
                        table=item.locator_table,
                        row=item.locator_row,
                        section=item.locator_section,
                        field=item.locator_field,
                        record_key=item.locator_record_key,
                    ),
                    inferred=item.inferred,
                )
                for item in evidence_rows
            ),
            recorded_at=_aware(row.recorded_at),
        )


def source_id_for_observation(session: Session, observation_id: str) -> str:
    from andromeda.infrastructure.database.models import KnowledgeSourceObservationModel

    observation = session.get(KnowledgeSourceObservationModel, observation_id)
    if observation is None:
        raise NotFoundError("Knowledge relation evidence observation does not exist")
    return observation.source_id


def _validate_interval_intersection(
    relation_interval: TemporalInterval,
    endpoint_intervals: tuple[tuple[datetime | None, datetime | None], ...],
) -> None:
    starts = tuple(
        bound
        for bound in (relation_interval.start, *(interval[0] for interval in endpoint_intervals))
        if bound is not None
    )
    ends = tuple(
        bound
        for bound in (relation_interval.end, *(interval[1] for interval in endpoint_intervals))
        if bound is not None
    )
    if starts and ends and max(starts) >= min(ends):
        raise ValidationError("Knowledge relation valid time does not overlap both endpoint revisions")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SqlAlchemyKnowledgeRelationRepository"]
