"""Quality contracts for semantic backfill and review gates."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.versions import SEMANTIC_CLASSIFIER_VERSION, SEMANTIC_TAXONOMY_VERSION


class SemanticQualityReport(ContractModel):
    semantic_version: str = SEMANTIC_TAXONOMY_VERSION
    classifier_version: str = SEMANTIC_CLASSIFIER_VERSION
    subject_count: int = Field(strict=True, ge=0)
    value_count: int = Field(strict=True, ge=0)
    available_count: int = Field(strict=True, ge=0)
    unresolved_count: int = Field(strict=True, ge=0)
    low_confidence_count: int = Field(strict=True, ge=0)
    rejected_count: int = Field(strict=True, ge=0)
    coverage: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    unresolved_rate: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    low_confidence_rate: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))


__all__ = ["SemanticQualityReport"]
