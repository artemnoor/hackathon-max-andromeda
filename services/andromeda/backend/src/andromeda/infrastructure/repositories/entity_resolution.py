"""SQLAlchemy catalog adapter for the transport-independent resolvers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.entity_resolution.repository.ports import EntityCatalogReader
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.universities.contracts.public import Direction, University
from andromeda.shared.contracts.enums import EducationLevel

from ..database.models import DirectionModel, DisciplineModel
from ..database.session import session_factory
from .disciplines import SqlAlchemyDisciplineRepository
from .programs import SqlAlchemyProgramRepository
from .universities import SqlAlchemyUniversityRepository


class SqlAlchemyEntityResolutionRepository(EntityCatalogReader):
    """Load canonical identity records in bounded catalog queries."""

    def __init__(self, engine: Any) -> None:
        self._factory = session_factory(engine)

    def list_universities(self) -> tuple[University, ...]:
        with self._factory() as session:
            return SqlAlchemyUniversityRepository(session).list()

    def list_directions(self) -> tuple[Direction, ...]:
        with self._factory() as session:
            rows = session.scalars(select(DirectionModel).order_by(DirectionModel.code, DirectionModel.id)).all()
            return tuple(
                Direction.model_validate(
                    {
                        "id": row.id,
                        "university_id": row.university_id,
                        "code": row.code,
                        "name": row.name,
                        "education_level": EducationLevel(row.education_level),
                    }
                )
                for row in rows
            )

    def list_programs(self) -> tuple[Program, ...]:
        with self._factory() as session:
            return SqlAlchemyProgramRepository(session).list()

    def list_disciplines(self) -> tuple[Discipline, ...]:
        with self._factory() as session:
            discipline_ids = tuple(session.scalars(select(DisciplineModel.id).order_by(DisciplineModel.normalized_name)).all())
            return tuple(SqlAlchemyDisciplineRepository(session).get_many(discipline_ids).values())


__all__ = ["SqlAlchemyEntityResolutionRepository"]
