from __future__ import annotations

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EducationYear, IngestRunId, SourceHash
from andromeda.shared.contracts.provenance import SourceAttribution


class BenefitProvenance(ContractModel):
    """Document-level evidence for a canonical admission-benefit fact."""

    source: SourceAttribution
    source_snapshot_hash: SourceHash
    source_run_id: IngestRunId
    admission_year: EducationYear
    document_title: str = Field(min_length=1, max_length=512)
    document_kind: str = Field(min_length=1, max_length=128)
    appendix_number: str | None = Field(default=None, min_length=1, max_length=32)
    page: int | None = Field(default=None, strict=True, ge=1)
    table: str | None = Field(default=None, min_length=1, max_length=256)
    row: int | None = Field(default=None, strict=True, ge=1)
    section: str | None = Field(default=None, min_length=1, max_length=512)
    parser_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_snapshot_identity(self) -> BenefitProvenance:
        if self.source.content_sha256 != self.source_snapshot_hash:
            raise ValueError("source snapshot hash must match source attribution hash")
        if self.source.run_id != self.source_run_id:
            raise ValueError("source run id must match source attribution run id")
        if not any((self.page, self.table, self.row, self.section, self.source.locator)):
            raise ValueError("benefit provenance requires a document locator")
        return self


__all__ = ["BenefitProvenance"]
