from __future__ import annotations

from ....shared.contracts.ids import DirectionId, UniversityId
from ..contracts.public import Direction, University
from ..repository.ports import UniversityReader


class UniversityReaderService:
    """Application-facing read service backed by a repository port."""

    def __init__(self, repository: UniversityReader) -> None:
        self._repository = repository

    def get(self, university_id: UniversityId) -> University | None:
        return self._repository.get(university_id)

    def list(self) -> tuple[University, ...]:
        return self._repository.list()

    def get_direction(self, direction_id: DirectionId) -> Direction | None:
        return self._repository.get_direction(direction_id)


__all__ = ["UniversityReaderService"]
