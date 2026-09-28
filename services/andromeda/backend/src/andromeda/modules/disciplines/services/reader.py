from __future__ import annotations

from ....shared.contracts.ids import DisciplineId
from ..contracts.public import Discipline
from ..repository.ports import DisciplineReader


class DisciplineReaderService:
    def __init__(self, reader: DisciplineReader) -> None:
        self._reader = reader

    def get(self, discipline_id: DisciplineId) -> Discipline | None:
        return self._reader.get(discipline_id)

    def list(self) -> tuple[Discipline, ...]:
        return self._reader.list()


__all__ = ["DisciplineReaderService"]
