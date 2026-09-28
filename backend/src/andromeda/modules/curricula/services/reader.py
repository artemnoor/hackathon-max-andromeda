from __future__ import annotations

from ....shared.contracts.ids import ProgramId
from ..contracts.public import Curriculum
from ..repository.ports import CurriculumReader


class CurriculumReaderService:
    """Application-facing curriculum reader backed by a port."""

    def __init__(self, reader: CurriculumReader) -> None:
        self._reader = reader

    def get_for_program(self, program_id: ProgramId) -> Curriculum | None:
        return self._reader.get_for_program(program_id)


__all__ = ["CurriculumReaderService"]
