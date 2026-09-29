from __future__ import annotations

from typing import Protocol

from ....shared.contracts.ids import DisciplineId
from ..contracts.public import Discipline


class DisciplineReader(Protocol):
    def get(self, discipline_id: DisciplineId) -> Discipline | None: ...

    def list(self) -> tuple[Discipline, ...]: ...


class DisciplineWriter(Protocol):
    def save(self, discipline: Discipline) -> None: ...


__all__ = ["DisciplineReader", "DisciplineWriter"]
