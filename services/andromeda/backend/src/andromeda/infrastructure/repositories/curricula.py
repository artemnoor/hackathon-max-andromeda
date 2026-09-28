from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem
from andromeda.modules.curricula.repository.ports import (
    CurriculumReader,
    CurriculumWriter,
)
from andromeda.shared.contracts.enums import AssessmentType, SourceKind
from andromeda.shared.contracts.errors import ContractError, ErrorCode
from andromeda.shared.contracts.ids import ProgramId, canonical_program_id
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference

from ..database.models import (
    CurriculumItemAssessmentModel,
    CurriculumItemModel,
    CurriculumItemSourceLinkModel,
    CurriculumModel,
    SourceSnapshotModel,
)


class SqlAlchemyCurriculumRepository(CurriculumReader, CurriculumWriter):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_program(self, program_id: ProgramId) -> Curriculum | None:
        resolved_program_id = canonical_program_id(program_id)
        model = self._session.execute(
            select(CurriculumModel).where(CurriculumModel.program_id == resolved_program_id).order_by(CurriculumModel.education_year.desc())
        ).scalars().first()
        if model is None:
            return None
        items = self._session.execute(
            select(CurriculumItemModel)
            .where(CurriculumItemModel.curriculum_id == model.id)
            .order_by(
                CurriculumItemModel.semester.is_(None),
                CurriculumItemModel.semester,
                CurriculumItemModel.source_position.is_(None),
                CurriculumItemModel.source_position,
                CurriculumItemModel.source_name,
            )
        ).scalars().all()
        assessments_by_item = _assessments_by_item(self._session, tuple(item.id for item in items))
        provenance_by_item = _provenance_by_item(self._session, tuple(item.id for item in items))
        return self._to_curriculum(
            model,
            items,
            assessments_by_item,
            provenance_by_item,
        )

    def list_for_programs(self, program_ids: tuple[ProgramId, ...]) -> dict[ProgramId, Curriculum]:
        """Load latest curricula, items, and assessments with bounded queries."""

        if not program_ids:
            return {}
        resolved_program_ids = tuple(canonical_program_id(program_id) for program_id in program_ids)
        models = self._session.execute(
            select(CurriculumModel)
            .where(CurriculumModel.program_id.in_(resolved_program_ids))
            .order_by(CurriculumModel.program_id, CurriculumModel.education_year.desc(), CurriculumModel.id)
        ).scalars().all()
        latest_by_program: dict[ProgramId, CurriculumModel] = {}
        for model in models:
            latest_by_program.setdefault(model.program_id, model)
        if not latest_by_program:
            return {}

        curriculum_ids = tuple(model.id for model in latest_by_program.values())
        items = self._session.execute(
            select(CurriculumItemModel)
            .where(CurriculumItemModel.curriculum_id.in_(curriculum_ids))
            .order_by(
                CurriculumItemModel.curriculum_id,
                CurriculumItemModel.semester.is_(None),
                CurriculumItemModel.semester,
                CurriculumItemModel.source_position.is_(None),
                CurriculumItemModel.source_position,
                CurriculumItemModel.source_name,
            )
        ).scalars().all()
        item_ids = tuple(item.id for item in items)
        assessments_by_item = _assessments_by_item(self._session, item_ids)
        provenance_by_item = _provenance_by_item(self._session, item_ids)
        items_by_curriculum: dict[str, list[CurriculumItemModel]] = defaultdict(list)
        for item in items:
            items_by_curriculum[item.curriculum_id].append(item)

        return {
            program_id: self._to_curriculum(
                model,
                items_by_curriculum[model.id],
                assessments_by_item,
                provenance_by_item,
            )
            for program_id, model in latest_by_program.items()
        }

    def _to_curriculum(
        self,
        model: CurriculumModel,
        items: Iterable[CurriculumItemModel],
        assessments_by_item: Mapping[str, Iterable[CurriculumItemAssessmentModel]],
        provenance_by_item: Mapping[str, tuple[SourceAttribution, ...]],
    ) -> Curriculum:
        return Curriculum.model_validate(
            {
                "id": model.id,
                "program_id": model.program_id,
                "education_year": model.education_year,
                "source_url": model.source_url,
                "captured_at": model.captured_at,
                "provenance": _provenance_values(model.provenance_json),
                "source_gaps": _gap_values(model.source_gaps_json),
                "items": tuple(
                    self._to_item(
                        item,
                        assessments_by_item.get(item.id, ()),
                        provenance_by_item.get(item.id, ()),
                    )
                    for item in items
                ),
            }
        )

    def save(self, curriculum: Curriculum) -> None:
        existing = self._session.get(CurriculumModel, curriculum.id)
        values = {
            "id": curriculum.id,
            "program_id": curriculum.program_id,
            "education_year": curriculum.education_year,
            "source_url": str(curriculum.source_url),
            "captured_at": curriculum.captured_at,
            "provenance_json": _provenance_json(curriculum.provenance),
            "source_gaps_json": _gap_json(curriculum.source_gaps),
        }
        if existing is None:
            self._session.add(CurriculumModel(**values))
        elif any(getattr(existing, key) != value for key, value in values.items() if key != "id"):
            raise ValueError(f"curriculum identity conflict: {curriculum.id}")

    def _to_item(
        self,
        model: CurriculumItemModel,
        assessment_rows: Iterable[CurriculumItemAssessmentModel] | None = None,
        provenance: tuple[SourceAttribution, ...] = (),
    ) -> CurriculumItem:
        if assessment_rows is None:
            assessment_rows = self._session.execute(
                select(CurriculumItemAssessmentModel).where(CurriculumItemAssessmentModel.curriculum_item_id == model.id)
            ).scalars().all()
        try:
            assessments = tuple(AssessmentType(row.assessment_type_id) for row in assessment_rows)
        except ValueError as exc:
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Persisted assessment type is not canonical") from exc
        return CurriculumItem.model_validate(
            {
                "id": model.id,
                "discipline_id": model.discipline_id,
                "source_name": model.source_name,
                "semester": model.semester,
                "hours": model.hours,
                "credits": model.credits,
                "assessment_types": assessments or None,
                "source_position": model.source_position,
                "lecture_hours": model.lecture_hours,
                "practice_hours": model.practice_hours,
                "lab_hours": model.lab_hours,
                "self_study_hours": model.self_study_hours,
                "is_elective": model.is_elective,
                "course_block": model.course_block,
                "practice_type": model.practice_type,
                "provenance": provenance,
            }
        )


def _provenance_json(values: tuple[SourceAttribution, ...]) -> str:
    return json.dumps([value.model_dump(mode="json") for value in values], ensure_ascii=False, separators=(",", ":"))


def _assessments_by_item(session: Session, item_ids: tuple[str, ...]) -> dict[str, tuple[CurriculumItemAssessmentModel, ...]]:
    if not item_ids:
        return {}
    rows = session.execute(
        select(CurriculumItemAssessmentModel).where(CurriculumItemAssessmentModel.curriculum_item_id.in_(item_ids))
    ).scalars().all()
    grouped: dict[str, list[CurriculumItemAssessmentModel]] = defaultdict(list)
    for row in rows:
        grouped[row.curriculum_item_id].append(row)
    return {key: tuple(value) for key, value in grouped.items()}


def _provenance_by_item(session: Session, item_ids: tuple[str, ...]) -> dict[str, tuple[SourceAttribution, ...]]:
    if not item_ids:
        return {}
    rows = session.execute(
        select(CurriculumItemSourceLinkModel, SourceSnapshotModel)
        .join(SourceSnapshotModel, SourceSnapshotModel.content_sha256 == CurriculumItemSourceLinkModel.source_sha256)
        .where(CurriculumItemSourceLinkModel.curriculum_item_id.in_(item_ids))
        .order_by(CurriculumItemSourceLinkModel.curriculum_item_id, CurriculumItemSourceLinkModel.link_id)
    ).all()
    grouped: dict[str, list[SourceAttribution]] = defaultdict(list)
    for link, snapshot in rows:
        try:
            attribution = SourceAttribution(
                kind=SourceKind(snapshot.source_kind),
                url=link.source_url,
                captured_at=snapshot.captured_at,
                content_sha256=link.source_sha256,
                locator=link.locator,
                university_id=link.university_id,
                run_id=link.ingest_run_id,
                field=link.field,
                record_key=link.record_key,
                inferred=link.inferred,
            )
        except ValueError as exc:
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Persisted source kind is not canonical") from exc
        grouped[link.curriculum_item_id].append(attribution)
    return {key: tuple(value) for key, value in grouped.items()}


def _gap_json(values: tuple[SourceGapReference, ...]) -> str:
    return json.dumps([value.model_dump(mode="json") for value in values], ensure_ascii=False, separators=(",", ":"))


def _provenance_values(value: str) -> tuple[SourceAttribution, ...]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("persisted curriculum provenance must be a list")
    return tuple(SourceAttribution.model_validate(item, strict=False) for item in parsed)


def _gap_values(value: str) -> tuple[SourceGapReference, ...]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("persisted curriculum source gaps must be a list")
    return tuple(SourceGapReference.model_validate(item, strict=False) for item in parsed)
