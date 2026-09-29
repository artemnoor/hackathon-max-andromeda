"""Typed inputs for semantic enrichment adapters."""

from __future__ import annotations

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    CurriculumItemId,
    DisciplineId,
    IngestRunId,
    ProgramId,
    SemanticVersion,
    ShortText,
    SourceHash,
)
from andromeda.shared.contracts.provenance import SourceAttribution


class SemanticClassificationInput(ContractModel):
    discipline_id: DisciplineId
    curriculum_item_id: CurriculumItemId | None = None
    program_id: ProgramId | None = None
    normalized_name: ShortText
    source_text: str | None = Field(default=None, max_length=4096)
    source_hash: SourceHash | None = None
    source_run_id: IngestRunId | None = None
    semantic_version: SemanticVersion | None = None
    provenance: tuple[SourceAttribution, ...] = Field(default=(), max_length=20)


__all__ = ["SemanticClassificationInput"]
