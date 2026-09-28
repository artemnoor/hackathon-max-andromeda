"""Infrastructure adapter for the Admission Fit reader port."""

from __future__ import annotations

import logging

from andromeda.modules.admission_fit.repository.ports import (
    AdmissionFitProgramData,
    BatchAdmissionFitDataReader,
)
from andromeda.modules.admissions.repository.ports import AdmissionReader
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.shared.contracts.ids import ProgramId

logger = logging.getLogger("andromeda.infrastructure.repositories.admission_fit")


class SqlAlchemyAdmissionFitReader(BatchAdmissionFitDataReader):
    """Compose existing public program/admissions readers without leaking ORM."""

    def __init__(self, programs: ProgramReader, admissions: AdmissionReader) -> None:
        self._programs = programs
        self._admissions = admissions

    def read(self, program_id: ProgramId) -> AdmissionFitProgramData | None:
        program = self._programs.get(program_id)
        if program is None:
            logger.warning("admission_fit_program_missing program_id=%s", program_id)
            return None
        admissions = self._admissions.get_for_program(program_id)
        logger.debug(
            "admission_fit_public_snapshot_read program_id=%s offerings=%d",
            program_id,
            len(admissions.offerings),
        )
        return AdmissionFitProgramData(program=program, admissions=admissions)

    def read_many(self, program_ids: tuple[ProgramId, ...]) -> dict[ProgramId, AdmissionFitProgramData]:
        requested = tuple(dict.fromkeys(program_ids))
        requested_set = set(requested)
        programs = {
            program.id: program
            for program in self._programs.list()
            if program.id in requested_set
        }
        get_many = getattr(self._admissions, "get_for_programs", None)
        if callable(get_many):
            admissions_by_program = {}
            ids = tuple(programs)
            for offset in range(0, len(ids), 400):
                admission_values = get_many(ids[offset : offset + 400])
                admissions_by_program.update({item.program_id: item for item in admission_values})
        else:
            admissions_by_program = {
                program_id: self._admissions.get_for_program(program_id)
                for program_id in programs
            }
        return {
            program_id: AdmissionFitProgramData(
                program=program,
                admissions=admissions_by_program[program_id],
            )
            for program_id, program in programs.items()
            if program_id in admissions_by_program
        }


__all__ = ["SqlAlchemyAdmissionFitReader"]
