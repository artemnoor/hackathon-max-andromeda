"""Storage ports for shared program projections."""

from __future__ import annotations

from typing import Protocol

from andromeda.shared.contracts.ids import ProgramId

from ..contracts.public import ProgramProjection, ProjectionBuild


class ProgramProjectionStore(Protocol):
    def save(self, builds: tuple[ProjectionBuild, ...]) -> None: ...


class ProgramProjectionReader(Protocol):
    def get(self, program_id: ProgramId) -> ProgramProjection | None: ...

    def list(self, *, program_ids: tuple[ProgramId, ...] = ()) -> tuple[ProgramProjection, ...]: ...


__all__ = ["ProgramProjectionReader", "ProgramProjectionStore"]
