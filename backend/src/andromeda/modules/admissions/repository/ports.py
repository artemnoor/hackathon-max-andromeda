"""Storage ports exposed by the admissions module."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from andromeda.shared.contracts.ids import EducationYear, ProgramId, UniversityId

from ..contracts.admission_cycles import AdmissionCycle, AdmissionCycleResolution
from ..contracts.offering_revisions import AdmissionOfferingRevision
from ..contracts.public import ProgramAdmissions


class AdmissionReader(Protocol):
    def get_for_program(self, program_id: ProgramId) -> ProgramAdmissions: ...


class BatchAdmissionReader(AdmissionReader, Protocol):
    """Optimized read boundary for candidate projections."""

    def get_for_programs(self, program_ids: tuple[ProgramId, ...]) -> tuple[ProgramAdmissions, ...]: ...


class AdmissionWriter(Protocol):
    def save(self, admissions: ProgramAdmissions) -> None: ...


class AdmissionRepository(AdmissionReader, AdmissionWriter, Protocol):
    """Combined port used only by composition and ingestion infrastructure."""


class AdmissionOfferingRevisionReader(Protocol):
    """Reads one exact immutable offering revision by owner ID, revision and hash."""

    def get_offering_revision(
        self,
        domain_rule_id: str,
        revision: int,
        content_hash: str,
    ) -> AdmissionOfferingRevision | None: ...


class AdmissionCycleReader(Protocol):
    def resolve_for_admission(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        *,
        as_known_at: datetime | None = None,
    ) -> AdmissionCycleResolution: ...


class AdmissionCycleWriter(Protocol):
    def append_approved_revision(self, cycle: AdmissionCycle) -> AdmissionCycle: ...


class AdmissionCycleRepository(AdmissionCycleReader, AdmissionCycleWriter, Protocol):
    """Append-only canonical cycle revisions and as-known-at reads."""


__all__ = [
    "AdmissionCycleReader",
    "AdmissionCycleRepository",
    "AdmissionCycleWriter",
    "AdmissionReader",
    "AdmissionOfferingRevisionReader",
    "AdmissionRepository",
    "AdmissionWriter",
    "BatchAdmissionReader",
]
