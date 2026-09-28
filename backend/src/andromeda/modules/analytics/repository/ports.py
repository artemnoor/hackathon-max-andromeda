"""Repository ports for materialized analytical projections."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from andromeda.shared.contracts.ids import ProgramId

from ..contracts.public import ProgramProjection, ProgramProjectionRun, ProjectionBuild


class ProgramProjectionStore(Protocol):
    def save(self, builds: Iterable[ProjectionBuild]) -> None: ...

    def mark_stale(self, program_ids: tuple[ProgramId, ...]) -> None: ...


class ProgramProjectionReader(Protocol):
    def get(self, program_id: ProgramId) -> ProgramProjection | None: ...

    def list(self, *, program_ids: tuple[ProgramId, ...] = ()) -> tuple[ProgramProjection, ...]: ...

    def read_by_program_ids(self, program_ids: tuple[ProgramId, ...]) -> tuple[ProgramProjection, ...]: ...


class ProgramProjectionRunStore(Protocol):
    def start_run(self, run: ProgramProjectionRun) -> ProgramProjectionRun: ...

    def complete_run(self, run_id: str, *, refreshed_program_count: int) -> ProgramProjectionRun: ...

    def fail_run(self, run_id: str, *, error_code: str, error_message: str) -> ProgramProjectionRun: ...


__all__ = ["ProgramProjectionReader", "ProgramProjectionRunStore", "ProgramProjectionStore"]
