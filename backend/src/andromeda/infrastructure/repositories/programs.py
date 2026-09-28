from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.programs.repository.ports import ProgramReader, ProgramWriter
from andromeda.shared.contracts.ids import ProgramId, UniversityId, canonical_program_id
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference

from ..database.models import DirectionModel, ProgramModel


class SqlAlchemyProgramRepository(ProgramReader, ProgramWriter):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, program_id: ProgramId) -> Program | None:
        model = self._session.get(ProgramModel, canonical_program_id(program_id))
        return _to_contract(model) if model is not None else None

    def list(self, university_id: UniversityId | None = None) -> tuple[Program, ...]:
        statement = select(ProgramModel).join(DirectionModel, ProgramModel.direction_id == DirectionModel.id)
        if university_id is not None:
            statement = statement.where(DirectionModel.university_id == university_id)
        models = self._session.execute(statement.order_by(ProgramModel.code, ProgramModel.id)).scalars().all()
        return tuple(_to_contract(model) for model in models)

    def save(self, program: Program) -> None:
        existing = self._session.get(ProgramModel, program.id)
        values = {
            "id": program.id,
            "direction_id": program.direction_id,
            "code": program.code,
            "name": program.name,
            "education_year": program.education_year,
            "study_plan_url": str(program.study_plan_url),
            "source_url": str(program.source_url),
            "provenance_json": _provenance_json(program.provenance),
            "source_gaps_json": _source_gaps_json(program.source_gaps),
        }
        if existing is None:
            self._session.add(ProgramModel(**values))
        elif any(getattr(existing, key) != value for key, value in values.items() if key != "id"):
            raise ValueError(f"program identity conflict: {program.id}")


def _to_contract(model: ProgramModel) -> Program:
    return Program.model_validate(
        {
            "id": model.id,
            "direction_id": model.direction_id,
            "code": model.code,
            "name": model.name,
            "education_year": model.education_year,
            "study_plan_url": model.study_plan_url,
            "source_url": model.source_url,
            "provenance": _provenance_values(model.provenance_json),
            "source_gaps": _source_gap_values(model.source_gaps_json),
        }
    )


def _provenance_json(values: tuple[SourceAttribution, ...]) -> str:
    return json.dumps([value.model_dump(mode="json") for value in values], ensure_ascii=False, separators=(",", ":"))


def _provenance_values(value: str) -> tuple[SourceAttribution, ...]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("persisted program provenance must be a list")
    return tuple(SourceAttribution.model_validate(item, strict=False) for item in parsed)


def _source_gaps_json(values: tuple[SourceGapReference, ...]) -> str:
    return json.dumps([value.model_dump(mode="json") for value in values], ensure_ascii=False, separators=(",", ":"))


def _source_gap_values(value: str) -> tuple[SourceGapReference, ...]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("persisted program source gaps must be a list")
    return tuple(SourceGapReference.model_validate(item, strict=False) for item in parsed)
