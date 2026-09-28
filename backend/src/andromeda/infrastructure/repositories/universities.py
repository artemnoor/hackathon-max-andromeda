from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.modules.universities.contracts.public import Direction, University
from andromeda.modules.universities.repository.ports import UniversityReader, UniversityWriter
from andromeda.shared.contracts.ids import DirectionId, UniversityId

from ..database.models import DirectionModel, UniversityModel


class SqlAlchemyUniversityRepository(UniversityReader, UniversityWriter):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, university_id: UniversityId) -> University | None:
        model = self._session.get(UniversityModel, university_id)
        if model is None:
            return None
        return University.model_validate(
            {"id": model.id, "name": model.name, "city": model.city, "official_site": model.official_site, "address": model.address}
        )

    def list(self) -> tuple[University, ...]:
        models = self._session.scalars(select(UniversityModel).order_by(UniversityModel.name, UniversityModel.id)).all()
        return tuple(
            University.model_validate(
                {"id": model.id, "name": model.name, "city": model.city, "official_site": model.official_site, "address": model.address}
            )
            for model in models
        )

    def get_direction(self, direction_id: DirectionId) -> Direction | None:
        model = self._session.get(DirectionModel, direction_id)
        if model is None:
            return None
        return Direction.model_validate(
            {
                "id": model.id,
                "university_id": model.university_id,
                "code": model.code,
                "name": model.name,
                "education_level": model.education_level,
            }
        )

    def save(self, university: University) -> None:
        existing = self._session.get(UniversityModel, university.id)
        values = {
            "id": university.id,
            "name": university.name,
            "city": university.city,
            "official_site": str(university.official_site),
            "address": university.address,
        }
        if existing is None:
            self._session.add(UniversityModel(**values))
        elif any(getattr(existing, key) != value for key, value in values.items() if key != "id"):
            raise ValueError(f"university identity conflict: {university.id}")
