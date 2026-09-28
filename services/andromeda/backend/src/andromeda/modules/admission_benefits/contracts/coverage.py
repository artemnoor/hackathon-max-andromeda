"""Coverage metadata shared by ingestion and admission-benefit consumers."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash


class AdmissionBenefitCoverageStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    REVIEW_REQUIRED = "review_required"
    UNAVAILABLE = "unavailable"


class AdmissionBenefitCoverage(ContractModel):
    status: AdmissionBenefitCoverageStatus = AdmissionBenefitCoverageStatus.PARTIAL
    documents_discovered: int = Field(default=0, strict=True, ge=0)
    documents_selected: int = Field(default=0, strict=True, ge=0)
    documents_captured: int = Field(default=0, strict=True, ge=0)
    documents_parsed: int = Field(default=0, strict=True, ge=0)
    required_documents_expected: int = Field(default=0, strict=True, ge=0)
    required_documents_discovered: int = Field(default=0, strict=True, ge=0)
    required_documents_captured: int = Field(default=0, strict=True, ge=0)
    records_normalized: int = Field(default=0, strict=True, ge=0)
    targets_resolved: int = Field(default=0, strict=True, ge=0)
    unresolved_targets: int = Field(default=0, strict=True, ge=0)
    conflicts: int = Field(default=0, strict=True, ge=0)
    review_required_rows: int = Field(default=0, strict=True, ge=0)
    manifest_hash: SourceHash | None = None
    source_hashes: tuple[SourceHash, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_selected_count(cls, data: object) -> object:
        if not isinstance(data, Mapping) or "documents_selected" in data:
            return data
        discovered = data.get("documents_discovered")
        if isinstance(discovered, int) and not isinstance(discovered, bool):
            return {**data, "documents_selected": discovered}
        return data

    @model_validator(mode="after")
    def validate_document_counts(self) -> AdmissionBenefitCoverage:
        if self.documents_selected > self.documents_discovered:
            raise ValueError("selected documents cannot exceed discovered documents")
        if self.documents_captured > self.documents_selected:
            raise ValueError("captured documents cannot exceed selected documents")
        if self.documents_parsed > self.documents_captured:
            raise ValueError("parsed documents cannot exceed captured documents")
        if self.required_documents_discovered > self.required_documents_expected:
            raise ValueError(
                "discovered required documents cannot exceed expected required documents"
            )
        if self.required_documents_captured > self.required_documents_discovered:
            raise ValueError(
                "captured required documents cannot exceed discovered required documents"
            )
        return self


__all__ = ["AdmissionBenefitCoverage", "AdmissionBenefitCoverageStatus"]
