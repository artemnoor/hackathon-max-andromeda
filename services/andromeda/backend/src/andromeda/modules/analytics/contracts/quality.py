"""Quality-aware basis selection results."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel

from ..domain.basis import MetricBasis
from .public import ProjectionDataQualityStatus


class BasisSelection(ContractModel):
    basis: MetricBasis | None
    coverage: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    status: ProjectionDataQualityStatus
    reason: str = Field(min_length=1, max_length=256)


__all__ = ["BasisSelection"]
