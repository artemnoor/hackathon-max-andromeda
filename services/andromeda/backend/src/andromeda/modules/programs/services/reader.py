from __future__ import annotations

from ....shared.contracts.ids import ProgramId
from ..contracts.public import Program
from ..repository.ports import ProgramReader


class ProgramReaderService:
    """Application-facing program reader; no storage details leak through."""

    def __init__(self, reader: ProgramReader) -> None:
        self._reader = reader

    def get(self, program_id: ProgramId) -> Program | None:
        return self._reader.get(program_id)

    def list(self) -> tuple[Program, ...]:
        return self._reader.list()


__all__ = ["ProgramReaderService"]
