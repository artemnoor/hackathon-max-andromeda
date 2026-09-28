from __future__ import annotations

from enum import StrEnum

from ....shared.contracts.base import ContractModel
from ....shared.contracts.ids import DisciplineId, ShortText


class IdentityResolutionStatus(StrEnum):
    NEW = "new"
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"


class IdentityResolution(ContractModel):
    source_name: str
    normalized_name: ShortText
    status: IdentityResolutionStatus
    discipline_id: DisciplineId | None = None
    candidate_ids: tuple[DisciplineId, ...] = ()
