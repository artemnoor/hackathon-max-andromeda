"""Application request contracts for future admission filters."""

from __future__ import annotations

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EducationYear, ProgramId


class AdmissionQuery(ContractModel):
    program_id: ProgramId
    admission_year: EducationYear | None = None


__all__ = ["AdmissionQuery"]
