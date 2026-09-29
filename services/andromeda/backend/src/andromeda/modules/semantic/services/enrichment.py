"""Application service that materializes semantic defaults and item values."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from hashlib import sha256

from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.shared.contracts.ids import IngestRunId, UniversityId

from ..contracts.inputs import SemanticClassificationInput
from ..contracts.ports import SemanticClassifierPort
from ..contracts.public import (
    CurriculumItemSemanticFeature,
    DisciplineSemanticDefault,
    SemanticEnrichmentRun,
    SemanticEnrichmentRunStatus,
)
from ..repository.ports import SemanticEnrichmentStore
from .classifier import merge_semantic_values

logger = logging.getLogger("andromeda.semantic.enrichment")


class SemanticEnrichmentService:
    """Build only affected semantic assignments after canonical commit."""

    def __init__(self, classifier: SemanticClassifierPort, store: SemanticEnrichmentStore) -> None:
        self._classifier = classifier
        self._store = store

    def enrich(
        self,
        *,
        university_id: UniversityId,
        ingest_run_id: IngestRunId,
        curricula: Iterable[Curriculum],
        disciplines: Iterable[Discipline],
        retry_of_run_id: str | None = None,
    ) -> SemanticEnrichmentRun:
        curricula_tuple = tuple(curricula)
        disciplines_by_id = {discipline.id: discipline for discipline in disciplines}
        items = tuple(item for curriculum in curricula_tuple for item in curriculum.items)
        item_ids = tuple(item.id for item in items)
        run_id = _run_id(ingest_run_id, self._classifier)
        run = self._store.start_run(
            run_id=run_id,
            ingest_run_id=ingest_run_id,
            university_id=university_id,
            semantic_version=_semantic_version(self._classifier),
            classifier_version=_classifier_version(self._classifier),
            affected_item_ids=item_ids,
            retry_of_run_id=retry_of_run_id,
        )
        if run.status is SemanticEnrichmentRunStatus.COMPLETED:
            logger.info("semantic_enrichment_idempotent run_id=%s status=completed", run.id)
            return run

        try:
            existing = self._store.item_source_hashes(
                item_ids,
                semantic_version=run.semantic_version,
                classifier_version=run.classifier_version,
            )
            changed_items = tuple(
                item
                for item in items
                if not _is_unchanged(item, existing.get(item.id, ()))
            )
            unchanged_count = len(items) - len(changed_items)
            defaults_by_discipline: dict[str, tuple[DisciplineSemanticDefault, ...]] = {}
            item_features: list[CurriculumItemSemanticFeature] = []
            for item in changed_items:
                discipline = disciplines_by_id.get(item.discipline_id)
                if discipline is None:
                    raise ValueError(f"Curriculum item discipline is missing: {item.discipline_id}")
                defaults = defaults_by_discipline.get(discipline.id)
                if defaults is None:
                    defaults = self._classify_defaults(discipline, item, ingest_run_id)
                    defaults_by_discipline[discipline.id] = defaults
                item_result = self._classifier.classify(
                    _classification_input(
                        discipline,
                        item,
                        ingest_run_id,
                        item_specific=True,
                    )
                )
                item_features.extend(
                    merge_semantic_values(
                        defaults,
                        item_result,
                        allow_inheritance=True,
                    )
                )

            self._store.save_discipline_defaults(
                value for defaults in defaults_by_discipline.values() for value in defaults
            )
            self._store.save_item_features(item_features)
            completed = self._store.complete_run(
                run.id,
                classified_item_count=len(changed_items),
                unchanged_item_count=unchanged_count,
                changed_item_ids=tuple(item.id for item in changed_items),
            )
            logger.info(
                "semantic_enrichment_completed run_id=%s affected_items=%d classified_items=%d unchanged_items=%d",
                completed.id,
                completed.affected_item_count,
                completed.classified_item_count,
                completed.unchanged_item_count,
            )
            return completed
        except Exception as exc:
            failed = self._store.fail_run(
                run.id,
                error_code=type(exc).__name__,
                error_message="Semantic enrichment failed; canonical data remains committed.",
                failed_item_count=1,
            )
            logger.exception("semantic_enrichment_failed run_id=%s status=%s", failed.id, failed.status)
            raise

    def _classify_defaults(
        self,
        discipline: Discipline,
        item: CurriculumItem,
        ingest_run_id: IngestRunId,
    ) -> tuple[DisciplineSemanticDefault, ...]:
        result = self._classifier.classify(
            _classification_input(discipline, item, ingest_run_id, item_specific=False)
        )
        return tuple(
            DisciplineSemanticDefault(discipline_id=discipline.id, feature=value)
            for value in result.values
        )


def _classification_input(
    discipline: Discipline,
    item: CurriculumItem,
    ingest_run_id: IngestRunId,
    *,
    item_specific: bool,
) -> SemanticClassificationInput:
    source_text = item.source_name if item_specific else discipline.name
    optional_context = " ".join(value for value in (item.course_block, item.practice_type) if value)
    if optional_context:
        source_text = f"{source_text} {optional_context}"
    return SemanticClassificationInput(
        discipline_id=discipline.id,
        curriculum_item_id=item.id if item_specific else None,
        normalized_name=discipline.normalized_name,
        source_text=source_text,
        source_hash=_item_source_hash(item),
        source_run_id=ingest_run_id,
        provenance=item.provenance,
    )


def _item_source_hash(item: CurriculumItem) -> str | None:
    return item.provenance[0].content_sha256 if item.provenance else None


def _is_unchanged(item: CurriculumItem, previous_hashes: tuple[str | None, ...]) -> bool:
    current_hash = _item_source_hash(item)
    return current_hash is not None and bool(previous_hashes) and set(previous_hashes) == {current_hash}


def _run_id(ingest_run_id: IngestRunId, classifier: SemanticClassifierPort) -> str:
    identity = f"{ingest_run_id}:{classifier.semantic_version}:{classifier.classifier_version}"
    return f"semantic-enrichment:{sha256(identity.encode('utf-8')).hexdigest()[:32]}"


def _semantic_version(classifier: SemanticClassifierPort) -> str:
    return classifier.semantic_version


def _classifier_version(classifier: SemanticClassifierPort) -> str:
    return classifier.classifier_version


__all__ = ["SemanticEnrichmentService"]
