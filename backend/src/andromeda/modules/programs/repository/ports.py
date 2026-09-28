from __future__ import annotations

from typing import Protocol

from ....shared.contracts.ids import ProgramId, UniversityId

from ..contracts.public import Program


class ProgramReader(Protocol):
    """Read-only program port consumed by application modules."""

    def get(self, program_id: ProgramId) -> Program | None: ...

    def list(self, university_id: UniversityId | None = None) -> tuple[Program, ...]: ...


class ProgramWriter(Protocol):
    def save(self, program: Program) -> None: ...


__all__ = ["ProgramReader", "ProgramWriter"]
