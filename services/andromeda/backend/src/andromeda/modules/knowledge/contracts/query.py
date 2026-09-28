"""Bounded source-claim lookup contracts for verified assistant queries."""

from __future__ import annotations

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel

from .claims import Claim
from .sources import KnowledgeSourceKind, SourceReliabilityTier


class KnowledgeClaimLookup(ContractModel):
    """An exact claim revision with reliability metadata for its origin source."""

    claim: Claim
    source_display_name: str = Field(min_length=1, max_length=256)
    source_kind: KnowledgeSourceKind
    source_reliability: SourceReliabilityTier


__all__ = ["KnowledgeClaimLookup"]
