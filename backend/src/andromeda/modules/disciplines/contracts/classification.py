from __future__ import annotations

from typing import Literal

from pydantic import Field

from ....shared.contracts.base import ContractModel
from ....shared.contracts.ids import DisciplineId, ShortText
from ..domain.areas import DisciplineAreaWeight


TAXONOMY_VERSION = "taxonomy-22.v1"
ClassificationMethod = Literal[
    "exact_override",
    "alias",
    "keyword_rule",
    "explicit_universal",
    "fallback",
    "unresolved",
]
ClassificationReviewStatus = Literal["reviewed", "automatic", "needs_review"]


class ClassificationOutcome(ContractModel):
    """Auditable result of mapping one source discipline to area weights."""

    discipline_id: DisciplineId
    source_name: str = Field(min_length=1, max_length=256)
    normalized_name: ShortText
    method: ClassificationMethod
    rule_id: ShortText | None = None
    taxonomy_version: ShortText = TAXONOMY_VERSION
    area_weights: tuple[DisciplineAreaWeight, ...] = Field(min_length=1)
    review_status: ClassificationReviewStatus


__all__ = [
    "ClassificationMethod",
    "ClassificationOutcome",
    "ClassificationReviewStatus",
    "TAXONOMY_VERSION",
]
