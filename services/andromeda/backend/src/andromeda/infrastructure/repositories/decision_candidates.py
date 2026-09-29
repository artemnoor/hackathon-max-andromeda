"""Canonical program/fingerprint adapter for decision orchestration."""

from __future__ import annotations

import logging

from andromeda.modules.admissions.repository.ports import BatchAdmissionReader
from andromeda.modules.admissions.contracts.public import ProgramAdmissions
from andromeda.modules.decision.repository.ports import ProgramCandidateSnapshot, ProgramCandidateSource
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.modules.proftest.contracts.public import ProgramFingerprint
from andromeda.modules.recommendations.contracts.public import ProgramFingerprintReader
from andromeda.modules.universities.repository.ports import UniversityReader
from andromeda.modules.universities.contracts.public import University
from andromeda.shared.contracts.ids import UniversityId
from andromeda.shared.contracts.errors import ContractError, ErrorCode


logger = logging.getLogger("andromeda.infrastructure.repositories.decision_candidates")


class CatalogDecisionCandidateSource(ProgramCandidateSource):
    """Join canonical program rows with existing curriculum fingerprints.

    Programs without a curriculum fingerprint stay in the returned snapshot
    with ``fingerprint=None``.  That preserves the source gap for Decision
    without pretending that a missing curriculum is an ineligible program.
    """

    def __init__(
        self,
        programs: ProgramReader,
        fingerprints: ProgramFingerprintReader,
        admissions: BatchAdmissionReader | None = None,
        universities: UniversityReader | None = None,
    ) -> None:
        self._programs = programs
        self._fingerprints = fingerprints
        self._admissions = admissions
        self._universities = universities

    def list_candidates(self) -> tuple[ProgramCandidateSnapshot, ...]:
        programs = tuple(sorted(self._programs.list(), key=lambda item: (item.code, item.id)))
        fingerprints = self._fingerprints.list_fingerprints()
        by_id: dict[str, ProgramFingerprint] = {}
        for fingerprint in fingerprints:
            if fingerprint.program_id in by_id:
                raise ContractError(ErrorCode.CONTRACT_ERROR, "Fingerprint source returned duplicate canonical program IDs")
            by_id[fingerprint.program_id] = fingerprint
        admissions_by_id = self._admissions_by_program(programs)
        universities_by_id = self._universities_by_id(programs)
        result = tuple(
            ProgramCandidateSnapshot(
                program=program,
                fingerprint=by_id.get(program.id),
                admissions=admissions_by_id.get(program.id),
                university=(
                    universities_by_id.get(university_id)
                    if (university_id := _university_id_for(program)) is not None
                    else None
                ),
            )
            for program in programs
        )
        logger.info(
            "decision_candidate_source_complete program_count=%d fingerprint_count=%d missing_fingerprint_count=%d admissions_count=%d university_count=%d",
            len(result),
            len(fingerprints),
            sum(item.fingerprint is None for item in result),
            sum(item.admissions is not None and bool(item.admissions.offerings) for item in result),
            len(universities_by_id),
        )
        return result

    def _admissions_by_program(self, programs: tuple[Program, ...]) -> dict[str, ProgramAdmissions]:
        if self._admissions is None:
            return {}
        program_ids = tuple(program.id for program in programs)
        return {item.program_id: item for item in self._admissions.get_for_programs(program_ids)}

    def _universities_by_id(self, programs: tuple[Program, ...]) -> dict[UniversityId, University]:
        if self._universities is None:
            return {}
        result: dict[UniversityId, University] = {}
        for program in programs:
            university_id = _university_id_for(program)
            if university_id is not None and university_id not in result:
                university = self._universities.get(university_id)
                if university is not None:
                    result[university_id] = university
        return result


def _university_id_for(program: Program) -> UniversityId | None:
    provenance = program.provenance
    for attribution in provenance:
        university_id = attribution.university_id
        if university_id is not None:
            return university_id
    direction_id = program.direction_id
    parts = direction_id.removeprefix("direction:").split(":", 1)
    if len(parts) == 2 and parts[0]:
        return f"university:{parts[0]}"
    return None


__all__ = ["CatalogDecisionCandidateSource"]
