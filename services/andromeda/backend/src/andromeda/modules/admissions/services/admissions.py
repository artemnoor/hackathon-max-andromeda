from __future__ import annotations

import logging

from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.ids import ProgramId

from ..contracts.results import ProgramAdmissionsResult
from ..repository.ports import AdmissionReader


logger = logging.getLogger("andromeda.admissions")


class AdmissionService:
    """Read use case for source-backed admissions of one canonical program."""

    def __init__(self, programs: ProgramReader, admissions: AdmissionReader) -> None:
        self._programs = programs
        self._admissions = admissions

    def get_for_program(self, program_id: ProgramId) -> ProgramAdmissionsResult:
        logger.debug("admissions_use_case_start program_id=%s", program_id)
        program = self._programs.get(program_id)
        if program is None:
            logger.warning("admissions_program_not_found program_id=%s", program_id)
            raise NotFoundError("Program was not found")
        admissions = self._admissions.get_for_program(program_id)
        result = ProgramAdmissionsResult(
            program=program,
            program_id=admissions.program_id,
            offerings=admissions.offerings,
        )
        logger.info("admissions_use_case_complete program_id=%s offerings=%d", program_id, len(result.offerings))
        return result


__all__ = ["AdmissionService"]
