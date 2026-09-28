"""SQLAlchemy adapter for semantic derived data and its independent lifecycle."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from andromeda.modules.semantic.contracts.public import (
    CurriculumItemSemanticFeature,
    DisciplineSemanticDefault,
    SemanticEnrichmentRun,
    SemanticEnrichmentRunStatus,
    SemanticFeatureDefinition,
    SemanticFeatureGroup,
    SemanticReviewStatus,
    SemanticValueType,
)
from andromeda.modules.semantic.repository.ports import SemanticEnrichmentStore
from andromeda.shared.contracts.ids import (
    CurriculumItemId,
    IngestRunId,
    SemanticVersion,
    UniversityId,
)
from andromeda.shared.contracts.provenance import SourceAttribution
from andromeda.shared.contracts.versions import SEMANTIC_TAXONOMY_VERSION

from ..database.models import (
    CurriculumItemSemanticFeatureModel,
    DisciplineSemanticFeatureModel,
    SemanticEnrichmentRunModel,
    SemanticFeatureModel,
)
from ..database.session import session_factory


class SqlAlchemySemanticEnrichmentRepository(SemanticEnrichmentStore):
    def __init__(self, engine: Any) -> None:
        self._factory = session_factory(engine)

    def list_features(self) -> tuple[SemanticFeatureDefinition, ...]:
        return self.list_active(SEMANTIC_TAXONOMY_VERSION)

    def list_active(self, definition_version: SemanticVersion) -> tuple[SemanticFeatureDefinition, ...]:
        with self._factory() as session:
            rows = session.scalars(
                select(SemanticFeatureModel)
                .where(
                    SemanticFeatureModel.definition_version == definition_version,
                    SemanticFeatureModel.active.is_(True),
                )
                .order_by(SemanticFeatureModel.code)
            ).all()
        return tuple(_to_feature(row) for row in rows)

    def get_by_codes(
        self,
        codes: tuple[str, ...],
        *,
        definition_version: SemanticVersion | None = None,
    ) -> tuple[SemanticFeatureDefinition, ...]:
        if not codes:
            return ()
        with self._factory() as session:
            query = select(SemanticFeatureModel).where(SemanticFeatureModel.code.in_(codes))
            if definition_version is not None:
                query = query.where(
                    SemanticFeatureModel.definition_version == definition_version,
                    SemanticFeatureModel.active.is_(True),
                )
            rows = session.scalars(query.order_by(SemanticFeatureModel.code)).all()
        return tuple(_to_feature(row) for row in rows)

    def start_run(
        self,
        *,
        run_id: str,
        ingest_run_id: IngestRunId,
        university_id: UniversityId,
        semantic_version: SemanticVersion,
        classifier_version: SemanticVersion,
        affected_item_ids: tuple[CurriculumItemId, ...],
        retry_of_run_id: str | None = None,
    ) -> SemanticEnrichmentRun:
        now = datetime.now(UTC)
        with self._factory() as session, session.begin():
            row = session.get(SemanticEnrichmentRunModel, run_id)
            if row is None:
                row = SemanticEnrichmentRunModel(
                    id=run_id,
                    ingest_run_id=ingest_run_id,
                    university_id=university_id,
                    status=SemanticEnrichmentRunStatus.RUNNING.value,
                    semantic_version=semantic_version,
                    classifier_version=classifier_version,
                    affected_item_ids_json=json.dumps(affected_item_ids, separators=(",", ":")),
                    affected_item_count=len(affected_item_ids),
                    started_at=now,
                    retry_of_run_id=retry_of_run_id,
                )
                session.add(row)
            elif row.status != SemanticEnrichmentRunStatus.COMPLETED.value:
                row.status = SemanticEnrichmentRunStatus.RUNNING.value
                row.ingest_run_id = ingest_run_id
                row.university_id = university_id
                row.semantic_version = semantic_version
                row.classifier_version = classifier_version
                row.affected_item_ids_json = json.dumps(affected_item_ids, separators=(",", ":"))
                row.affected_item_count = len(affected_item_ids)
                row.classified_item_count = 0
                row.unchanged_item_count = 0
                row.failed_item_count = 0
                row.started_at = now
                row.finished_at = None
                row.retry_of_run_id = retry_of_run_id
                row.error_code = None
                row.error_message = None
            session.flush()
            return _to_run(row)

    def item_source_hashes(
        self,
        item_ids: tuple[CurriculumItemId, ...],
        *,
        semantic_version: SemanticVersion,
        classifier_version: SemanticVersion,
    ) -> dict[CurriculumItemId, tuple[str | None, ...]]:
        if not item_ids:
            return {}
        with self._factory() as session:
            rows = session.execute(
                select(
                    CurriculumItemSemanticFeatureModel.curriculum_item_id,
                    CurriculumItemSemanticFeatureModel.source_hash,
                ).where(
                    CurriculumItemSemanticFeatureModel.curriculum_item_id.in_(item_ids),
                    CurriculumItemSemanticFeatureModel.semantic_version == semantic_version,
                    CurriculumItemSemanticFeatureModel.classifier_version == classifier_version,
                )
            ).all()
        grouped: dict[CurriculumItemId, list[str | None]] = defaultdict(list)
        for item_id, source_hash in rows:
            if source_hash not in grouped[item_id]:
                grouped[item_id].append(source_hash)
        return {item_id: tuple(values) for item_id, values in grouped.items()}

    def item_features(
        self,
        item_ids: tuple[CurriculumItemId, ...],
        *,
        semantic_version: SemanticVersion,
        classifier_version: SemanticVersion,
    ) -> dict[CurriculumItemId, tuple[CurriculumItemSemanticFeature, ...]]:
        if not item_ids:
            return {}
        with self._factory() as session:
            rows = session.scalars(
                select(CurriculumItemSemanticFeatureModel).where(
                    CurriculumItemSemanticFeatureModel.curriculum_item_id.in_(item_ids),
                    CurriculumItemSemanticFeatureModel.semantic_version == semantic_version,
                    CurriculumItemSemanticFeatureModel.classifier_version == classifier_version,
                )
            ).all()
        grouped: dict[CurriculumItemId, list[CurriculumItemSemanticFeature]] = defaultdict(list)
        for row in rows:
            grouped[row.curriculum_item_id].append(_to_item_feature(row))
        return {item_id: tuple(values) for item_id, values in grouped.items()}

    def save_discipline_defaults(self, values: Iterable[DisciplineSemanticDefault]) -> None:
        defaults = tuple(values)
        if not defaults:
            return
        groups: dict[tuple[SemanticVersion, SemanticVersion], list[DisciplineSemanticDefault]] = defaultdict(list)
        for value in defaults:
            groups[(value.feature.semantic_version, value.feature.classifier_version)].append(value)
        with self._factory() as session, session.begin():
            mappings: list[dict[str, object]] = []
            for (semantic_version, classifier_version), group in groups.items():
                discipline_ids = tuple({value.discipline_id for value in group})
                session.execute(
                    delete(DisciplineSemanticFeatureModel).where(
                        DisciplineSemanticFeatureModel.discipline_id.in_(discipline_ids),
                        DisciplineSemanticFeatureModel.semantic_version == semantic_version,
                        DisciplineSemanticFeatureModel.classifier_version == classifier_version,
                    )
                )
                mappings.extend(
                    _discipline_mapping(value)
                    for value in group
                )
            session.execute(insert(DisciplineSemanticFeatureModel), mappings)

    def save_item_features(self, values: Iterable[CurriculumItemSemanticFeature]) -> None:
        features = tuple(values)
        if not features:
            return
        groups: dict[tuple[SemanticVersion, SemanticVersion], list[CurriculumItemSemanticFeature]] = defaultdict(list)
        for value in features:
            groups[(value.feature.semantic_version, value.feature.classifier_version)].append(value)
        with self._factory() as session, session.begin():
            mappings: list[dict[str, object]] = []
            for (semantic_version, classifier_version), group in groups.items():
                item_ids = tuple({value.curriculum_item_id for value in group})
                session.execute(
                    delete(CurriculumItemSemanticFeatureModel).where(
                        CurriculumItemSemanticFeatureModel.curriculum_item_id.in_(item_ids),
                        CurriculumItemSemanticFeatureModel.semantic_version == semantic_version,
                        CurriculumItemSemanticFeatureModel.classifier_version == classifier_version,
                    )
                )
                mappings.extend(_item_mapping(value) for value in group)
            session.execute(insert(CurriculumItemSemanticFeatureModel), mappings)

    def complete_run(
        self,
        run_id: str,
        *,
        classified_item_count: int,
        unchanged_item_count: int,
        changed_item_ids: tuple[CurriculumItemId, ...] = (),
    ) -> SemanticEnrichmentRun:
        with self._factory() as session, session.begin():
            row = _required_run(session, run_id)
            row.status = SemanticEnrichmentRunStatus.COMPLETED.value
            row.classified_item_count = classified_item_count
            row.unchanged_item_count = unchanged_item_count
            row.changed_item_ids_json = json.dumps(changed_item_ids, separators=(",", ":"))
            row.finished_at = datetime.now(UTC)
            row.error_code = None
            row.error_message = None
            session.flush()
            return _to_run(row)

    def fail_run(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
        failed_item_count: int,
    ) -> SemanticEnrichmentRun:
        with self._factory() as session, session.begin():
            row = _required_run(session, run_id)
            row.status = SemanticEnrichmentRunStatus.FAILED.value
            row.failed_item_count = failed_item_count
            row.finished_at = datetime.now(UTC)
            row.error_code = error_code[:64]
            row.error_message = error_message[:512]
            session.flush()
            return _to_run(row)


def _required_run(session: Session, run_id: str) -> SemanticEnrichmentRunModel:
    row = session.get(SemanticEnrichmentRunModel, run_id)
    if row is None:
        raise ValueError(f"semantic enrichment run does not exist: {run_id}")
    return row


def _discipline_mapping(value: DisciplineSemanticDefault) -> dict[str, object]:
    feature = value.feature
    return {
        "discipline_id": value.discipline_id,
        "feature_id": feature.feature_id,
        "semantic_version": feature.semantic_version,
        "classifier_version": feature.classifier_version,
        "value": feature.value,
        "status": feature.status.value,
        "confidence": feature.confidence,
        "classification_method": feature.classification_method.value,
        "review_status": feature.review_status.value,
        "source_hash": feature.source_hash,
        "source_run_id": feature.source_run_id,
        "evidence_json": _json(feature.evidence),
        "provenance_json": _json(feature.provenance),
        "created_at": feature.created_at,
    }


def _item_mapping(value: CurriculumItemSemanticFeature) -> dict[str, object]:
    feature = value.feature
    return {
        "curriculum_item_id": value.curriculum_item_id,
        "feature_id": feature.feature_id,
        "semantic_version": feature.semantic_version,
        "classifier_version": feature.classifier_version,
        "value": feature.value,
        "status": feature.status.value,
        "confidence": feature.confidence,
        "classification_method": feature.classification_method.value,
        "review_status": feature.review_status.value,
        "source_hash": feature.source_hash,
        "source_run_id": feature.source_run_id,
        "evidence_json": _json(feature.evidence),
        "provenance_json": _json(feature.provenance),
        "overrides_discipline_default": value.overrides_discipline_default,
        "created_at": feature.created_at,
    }


def _to_item_feature(row: CurriculumItemSemanticFeatureModel) -> CurriculumItemSemanticFeature:
    from andromeda.modules.semantic.contracts.public import (
        SemanticClassificationEvidence,
        SemanticClassificationMethod,
        SemanticFeatureValue,
        SemanticValueStatus,
    )

    evidence = json.loads(row.evidence_json)
    provenance = json.loads(row.provenance_json)
    if not isinstance(evidence, list) or not isinstance(provenance, list):
        raise ValueError("semantic assignment evidence must be JSON arrays")
    feature = SemanticFeatureValue(
        feature_id=row.feature_id,
        value=row.value,
        status=SemanticValueStatus(row.status),
        confidence=row.confidence,
        classification_method=SemanticClassificationMethod(row.classification_method),
        review_status=SemanticReviewStatus(row.review_status),
        classifier_version=row.classifier_version,
        semantic_version=row.semantic_version,
        source_hash=row.source_hash,
        source_run_id=row.source_run_id,
        created_at=row.created_at,
        evidence=tuple(SemanticClassificationEvidence.model_validate(item, strict=False) for item in evidence),
        provenance=tuple(_source_attribution(item) for item in provenance),
    )
    return CurriculumItemSemanticFeature(
        curriculum_item_id=row.curriculum_item_id,
        feature=feature,
        overrides_discipline_default=row.overrides_discipline_default,
    )


def _to_feature(row: SemanticFeatureModel) -> SemanticFeatureDefinition:
    return SemanticFeatureDefinition(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        feature_group=SemanticFeatureGroup(row.feature_group),
        value_type=SemanticValueType(row.value_type),
        definition_version=row.definition_version,
        semantic_version=row.semantic_version,
        active=row.active,
        retired_at=row.retired_at,
    )


def _source_attribution(value: object) -> SourceAttribution:
    if not isinstance(value, dict):
        raise ValueError("semantic provenance item must be an object")
    return SourceAttribution.model_validate(value, strict=False)


def _json(values: Sequence[Any]) -> str:
    return json.dumps(
        [value.model_dump(mode="json") for value in values],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _to_run(row: SemanticEnrichmentRunModel) -> SemanticEnrichmentRun:
    item_ids = json.loads(row.affected_item_ids_json)
    changed_item_ids = json.loads(row.changed_item_ids_json or "[]")
    if not isinstance(item_ids, list) or not isinstance(changed_item_ids, list):
        raise ValueError("semantic enrichment affected IDs must be a list")
    return SemanticEnrichmentRun.model_validate(
        {
            "id": row.id,
            "ingest_run_id": row.ingest_run_id,
            "university_id": row.university_id,
            "status": SemanticEnrichmentRunStatus(row.status),
            "semantic_version": row.semantic_version,
            "classifier_version": row.classifier_version,
            "affected_item_ids": tuple(item_ids),
            "changed_item_ids": tuple(changed_item_ids),
            "affected_item_count": row.affected_item_count,
            "classified_item_count": row.classified_item_count,
            "unchanged_item_count": row.unchanged_item_count,
            "failed_item_count": row.failed_item_count,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "retry_of_run_id": row.retry_of_run_id,
            "error_code": row.error_code,
            "error_message": row.error_message,
        }
    )


__all__ = ["SqlAlchemySemanticEnrichmentRepository"]
