from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from andromeda.api.dependencies import get_curriculum_reader, get_discipline_reader, get_program_reader, get_university_reader
from andromeda.api.schemas.common import CurriculumItemResponse, CurriculumResponse, ProgramListResponse, ProgramResponse, ProgramSummaryResponse, SourceAttributionResponse, SourceGapReferenceResponse
from andromeda.api.schemas.disciplines import discipline_response
from andromeda.modules.curricula.repository.ports import CurriculumReader
from andromeda.modules.disciplines.repository.ports import DisciplineReader
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.modules.universities.repository.ports import UniversityReader
from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.ids import ProgramId

router = APIRouter(prefix="/programs", tags=["programs"])


def _university_id(program: Program) -> str | None:
    parts = program.direction_id.split(":")
    return f"university:{parts[1]}" if len(parts) == 3 else None


def _summary(program: Program, universities: UniversityReader | None = None) -> ProgramSummaryResponse:
    university_id = _university_id(program)
    university = universities.get(university_id) if universities is not None and university_id is not None else None
    return ProgramSummaryResponse.model_validate(
        {
            **program.model_dump(),
            "university_id": university_id,
            "university_name": university.name if university is not None else None,
        }
    )


@router.get("", response_model=ProgramListResponse)
def list_programs(
    university_id: str | None = Query(default=None, alias="universityId"),
    programs: ProgramReader = Depends(get_program_reader),
    universities: UniversityReader = Depends(get_university_reader),
) -> ProgramListResponse:
    return ProgramListResponse(
        items=tuple(_summary(program, universities) for program in programs.list(university_id=university_id))
    )


@router.get("/{id}", response_model=ProgramResponse)
def get_program(
    id: ProgramId,
    programs: ProgramReader = Depends(get_program_reader),
    universities: UniversityReader = Depends(get_university_reader),
) -> ProgramResponse:
    program = programs.get(id)
    if program is None:
        raise NotFoundError("Program was not found")
    return ProgramResponse(program=_summary(program, universities))


@router.get("/{id}/curriculum", response_model=CurriculumResponse)
def get_curriculum(
    id: ProgramId,
    programs: ProgramReader = Depends(get_program_reader),
    curricula: CurriculumReader = Depends(get_curriculum_reader),
    disciplines: DisciplineReader = Depends(get_discipline_reader),
    universities: UniversityReader = Depends(get_university_reader),
) -> CurriculumResponse:
    program = programs.get(id)
    if program is None:
        raise NotFoundError("Program was not found")
    curriculum = curricula.get_for_program(id)
    if curriculum is None:
        raise NotFoundError("Curriculum was not found")
    items: list[CurriculumItemResponse] = []
    for item in curriculum.items:
        discipline = disciplines.get(item.discipline_id)
        if discipline is None:
            raise RuntimeError("Curriculum item discipline is missing")
        items.append(
            CurriculumItemResponse(
                id=item.id,
                discipline=discipline_response(discipline),
                source_name=item.source_name,
                semester=item.semester,
                hours=item.hours,
                credits=item.credits,
                assessment_types=item.assessment_types,
                source_position=item.source_position,
            )
        )
    return CurriculumResponse(
        program=_summary(program, universities),
        curriculum_id=curriculum.id,
        education_year=curriculum.education_year,
        source_url=curriculum.source_url,
        captured_at=curriculum.captured_at,
        items=tuple(items),
        provenance=tuple(SourceAttributionResponse.model_validate(item.model_dump()) for item in curriculum.provenance),
        source_gaps=tuple(SourceGapReferenceResponse.model_validate(item.model_dump()) for item in curriculum.source_gaps),
    )
