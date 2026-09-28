"""Read-only catalog port for bounded resolver indexes."""

from __future__ import annotations

from typing import Protocol

from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.universities.contracts.public import Direction, University


class EntityCatalogReader(Protocol):
    def list_universities(self) -> tuple[University, ...]: ...

    def list_directions(self) -> tuple[Direction, ...]: ...

    def list_programs(self) -> tuple[Program, ...]: ...

    def list_disciplines(self) -> tuple[Discipline, ...]: ...


__all__ = ["EntityCatalogReader"]
