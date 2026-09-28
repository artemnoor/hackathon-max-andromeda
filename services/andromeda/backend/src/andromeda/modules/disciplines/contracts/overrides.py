from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from ....shared.contracts.base import ContractModel
from ....shared.contracts.ids import ShortText, SourceHash, UniversityId
from ..domain.areas import DisciplineAreaWeight


OverrideReviewState = Literal["draft", "approved", "rejected"]
UnknownReviewState = Literal["unreviewed", "reviewed"]


class TaxonomyOverride(ContractModel):
    """One reviewed, adapter-owned taxonomy correction."""

    normalized_key: ShortText
    university_id: UniversityId
    source_alias: ShortText | None = None
    area_weights: tuple[DisciplineAreaWeight, ...] = Field(min_length=1)
    reason: ShortText
    owner: ShortText
    created_at: datetime
    taxonomy_version: ShortText
    review_state: OverrideReviewState = "draft"
    reviewed_by: ShortText | None = None
    reviewed_at: datetime | None = None
    affected_source_count: int = Field(default=0, strict=True, ge=0)
    blocking: bool = False

    @model_validator(mode="after")
    def validate_review_metadata(self) -> Self:
        if self.source_alias == self.normalized_key:
            raise ValueError("taxonomy source_alias must differ from normalized_key")
        requires_review_identity = self.review_state == "approved" and (
            self.blocking or self.affected_source_count >= 100
        )
        if requires_review_identity and (self.reviewed_by is None or self.reviewed_at is None):
            raise ValueError("high-volume or blocking taxonomy overrides require review metadata")
        if self.review_state == "rejected" and self.reviewed_by is None:
            raise ValueError("rejected taxonomy overrides require reviewer identity")
        return self


class TaxonomyRegressionCase(ContractModel):
    normalized_name: ShortText
    area_weights: tuple[DisciplineAreaWeight, ...] = Field(min_length=1)


class TaxonomyOverrideArtifact(ContractModel):
    university_id: UniversityId
    taxonomy_version: ShortText
    content_sha256: SourceHash
    overrides: tuple[TaxonomyOverride, ...] = ()
    regression_cases: tuple[TaxonomyRegressionCase, ...] = ()


class UnknownClassification(ContractModel):
    normalized_name: ShortText
    university_id: UniversityId
    source_count: int = Field(strict=True, ge=1)
    affected_programs: tuple[str, ...] = ()
    first_seen_run_id: str = Field(min_length=1, max_length=64)
    last_seen_run_id: str = Field(min_length=1, max_length=64)
    review_state: UnknownReviewState = "unreviewed"


__all__ = [
    "OverrideReviewState",
    "TaxonomyOverride",
    "TaxonomyOverrideArtifact",
    "TaxonomyRegressionCase",
    "UnknownClassification",
    "UnknownReviewState",
]
