"""Typed read ports used by the analytics executor."""

from __future__ import annotations

from typing import Protocol, Any

from andromeda.shared.contracts.ids import ProgramId, SemanticVersion

from ..contracts.public import ProgramProjection, ProjectionMetricEvidence
from ..contracts.query import QuerySpec


class ProjectionQueryReader(Protocol):
    def list(self, *, program_ids: tuple[ProgramId, ...] = ()) -> tuple[ProgramProjection, ...]: ...

    def query(self, spec: QuerySpec, *, registry: Any | None = None) -> tuple[ProgramProjection, ...]: ...

    def evidence(
        self,
        program_ids: tuple[ProgramId, ...],
        *,
        metric_codes: tuple[str, ...],
        schema_version: SemanticVersion,
    ) -> tuple[ProjectionMetricEvidence, ...]: ...


__all__ = ["ProjectionQueryReader"]
