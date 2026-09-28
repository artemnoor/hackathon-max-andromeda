from __future__ import annotations

from typing import Protocol

from ....shared.contracts.ids import DirectionId, UniversityId
from ..contracts.public import Direction, University


class UniversityRepository(Protocol):
    def get(self, university_id: UniversityId) -> University | None: ...

    def list(self) -> tuple[University, ...]: ...

    def get_direction(self, direction_id: DirectionId) -> Direction | None: ...


class UniversityReader(UniversityRepository, Protocol):
    """Read-only contract exposed to application modules."""


class UniversityWriter(Protocol):
    def save(self, university: University) -> None: ...


__all__ = ["UniversityReader", "UniversityRepository"]
