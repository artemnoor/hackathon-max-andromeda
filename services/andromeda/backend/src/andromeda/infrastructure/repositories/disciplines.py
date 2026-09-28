from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.modules.disciplines.contracts.public import Discipline, DisciplineAreaCode, DisciplineAreaWeight, area_catalog
from andromeda.modules.disciplines.repository.ports import DisciplineReader, DisciplineWriter
from andromeda.shared.contracts.ids import DisciplineId

from ..database.models import DisciplineAreaModel, DisciplineAreaWeightModel, DisciplineModel


class SqlAlchemyDisciplineRepository(DisciplineReader, DisciplineWriter):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, discipline_id: DisciplineId) -> Discipline | None:
        model = self._session.get(DisciplineModel, discipline_id)
        return self._to_contract(model) if model is not None else None

    def list(self) -> tuple[Discipline, ...]:
        models = self._session.execute(select(DisciplineModel).order_by(DisciplineModel.normalized_name)).scalars().all()
        return tuple(self._to_contract(model) for model in models)

    def get_many(self, discipline_ids: Collection[DisciplineId]) -> dict[DisciplineId, Discipline]:
        """Load disciplines and all area weights with two bounded queries."""

        ids = tuple(dict.fromkeys(discipline_ids))
        if not ids:
            return {}
        models = self._session.execute(
            select(DisciplineModel).where(DisciplineModel.id.in_(ids)).order_by(DisciplineModel.normalized_name)
        ).scalars().all()
        weight_rows = self._session.execute(
            select(DisciplineAreaWeightModel)
            .where(DisciplineAreaWeightModel.discipline_id.in_(ids))
            .order_by(DisciplineAreaWeightModel.discipline_id, DisciplineAreaWeightModel.area_id)
        ).scalars().all()
        weights_by_discipline: dict[str, list[DisciplineAreaWeightModel]] = {}
        for row in weight_rows:
            weights_by_discipline.setdefault(row.discipline_id, []).append(row)
        return {
            model.id: self._to_contract(model, weights_by_discipline.get(model.id, ()))
            for model in models
        }

    def save(self, discipline: Discipline) -> None:
        existing = self._session.get(DisciplineModel, discipline.id)
        values = {"id": discipline.id, "name": discipline.name, "normalized_name": discipline.normalized_name}
        if existing is None:
            self._session.add(DisciplineModel(**values))
        elif any(getattr(existing, key) != value for key, value in values.items() if key != "id"):
            raise ValueError(f"discipline identity conflict: {discipline.id}")
        for definition in area_catalog():
            if self._session.get(DisciplineAreaModel, definition.code.value) is None:
                self._session.add(
                    DisciplineAreaModel(
                        id=definition.code.value,
                        name=definition.name,
                        description=definition.description,
                        position=definition.position,
                    )
                )
        self._session.flush()
        existing_weights = {
            row.area_id: row.weight
            for row in self._session.execute(
                select(DisciplineAreaWeightModel).where(DisciplineAreaWeightModel.discipline_id == discipline.id)
            ).scalars().all()
        }
        expected_weights = {weight.area.value: weight.weight for weight in discipline.area_weights}
        if set(existing_weights) - set(expected_weights):
            raise ValueError(f"discipline area identity conflict: {discipline.id}")
        for area_id, weight in expected_weights.items():
            stored = existing_weights.get(area_id)
            if stored is None:
                self._session.add(DisciplineAreaWeightModel(discipline_id=discipline.id, area_id=area_id, weight=weight))
            elif stored != weight:
                raise ValueError(f"discipline area identity conflict: {discipline.id}")

    def _to_contract(self, model: DisciplineModel, rows: Collection[DisciplineAreaWeightModel] | None = None) -> Discipline:
        if rows is None:
            rows = self._session.execute(
                select(DisciplineAreaWeightModel)
                .where(DisciplineAreaWeightModel.discipline_id == model.id)
                .order_by(DisciplineAreaWeightModel.area_id)
            ).scalars().all()
        area_weights = tuple(
            DisciplineAreaWeight(area=DisciplineAreaCode(row.area_id), weight=row.weight)
            for row in rows
        )
        return Discipline.model_validate(
            {
                "id": model.id,
                "name": model.name,
                "normalized_name": model.normalized_name,
                "area_weights": area_weights,
            }
        )
