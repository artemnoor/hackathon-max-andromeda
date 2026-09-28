"""Storage ports for semantic assignments; ORM stays in infrastructure."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from andromeda.shared.contracts.ids import (
    CurriculumItemId,
    IngestRunId,
    SemanticVersion,
    UniversityId,
)

from ..contracts.public import (
    CurriculumItemSemanticFeature,
    DisciplineSemanticDefault,
    SemanticEnrichmentRun,
    SemanticFeature,
    SemanticFeatureDefinition,
    SemanticFeatureRegistryPort,
)


class SemanticFeatureCatalogReader(SemanticFeatureRegistryPort, Protocol):
    def list_features(self) -> tuple[SemanticFeature, ...]:
        """Return the versioned allow-list used by classifiers."""


class SemanticAssignmentWriter(Protocol):
    def save_discipline_defaults(self, values: Iterable[DisciplineSemanticDefault]) -> None:
        """Persist reusable discipline-level semantic values."""

    def save_item_features(self, values: Iterable[CurriculumItemSemanticFeature]) -> None:
        """Persist context-specific item values and overrides."""


class SemanticEnrichmentStore(SemanticAssignmentWriter, Protocol):
    def item_features(
        self,
        item_ids: tuple[CurriculumItemId, ...],
        *,
        semantic_version: SemanticVersion,
        classifier_version: SemanticVersion,
    ) -> dict[CurriculumItemId, tuple[CurriculumItemSemanticFeature, ...]]:
        """Read current-version assignments in one bounded query."""

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
        """Create or resume an independent derived-data run."""

    def item_source_hashes(
        self,
        item_ids: tuple[CurriculumItemId, ...],
        *,
        semantic_version: SemanticVersion,
        classifier_version: SemanticVersion,
    ) -> dict[CurriculumItemId, tuple[str | None, ...]]:
        """Read current-version assignments in one bounded query."""

    def complete_run(
        self,
        run_id: str,
        *,
        classified_item_count: int,
        unchanged_item_count: int,
        changed_item_ids: tuple[CurriculumItemId, ...] = (),
    ) -> SemanticEnrichmentRun:
        """Mark derived data complete without mutating canonical run health."""

    def fail_run(self, run_id: str, *, error_code: str, error_message: str, failed_item_count: int) -> SemanticEnrichmentRun:
        """Make a failed derived run visible and retryable."""


__all__ = ["SemanticAssignmentWriter", "SemanticEnrichmentStore", "SemanticFeatureCatalogReader"]
