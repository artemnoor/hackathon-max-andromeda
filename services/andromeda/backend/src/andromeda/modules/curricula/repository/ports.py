from __future__ import annotations

from typing import Protocol

from ....shared.contracts.ids import ProgramId

from ..contracts.public import Curriculum


class CurriculumReader(Protocol):
    """Read-only curriculum port consumed by comparison."""

    def get_for_program(self, program_id: ProgramId) -> Curriculum | None: ...


class CurriculumWriter(Protocol):
    def save(self, curriculum: Curriculum) -> None: ...


__all__ = ["CurriculumReader", "CurriculumWriter"]
