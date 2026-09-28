from __future__ import annotations

import pytest

from andromeda.modules.comparison.contracts.public import ComparisonSummaryRequest
from andromeda.modules.comparison.services.compare_programs import CompareProgramsService
from andromeda.modules.comparison.services.compare_summary import ComparisonSummaryService


class ProgramReaderStub:
    def __init__(self, programs):
        self.programs = tuple(programs)

    def get(self, program_id):
        return next((program for program in self.programs if program.id == program_id), None)

    def list(self):
        return self.programs


class CurriculumReaderStub:
    def __init__(self, curricula):
        self.curricula = {curriculum.program_id: curriculum for curriculum in curricula}

    def get_for_program(self, program_id):
        return self.curricula.get(program_id)


class DisciplineReaderStub:
    def __init__(self, disciplines):
        self.disciplines = {discipline.id: discipline for discipline in disciplines}

    def get(self, discipline_id):
        return self.disciplines.get(discipline_id)

    def list(self):
        return tuple(self.disciplines.values())


def make_service(parsed_bundle):
    _, snapshot = parsed_bundle
    programs = list(snapshot.programs)
    curricula = list(snapshot.curricula)
    disciplines = DisciplineReaderStub(snapshot.disciplines)
    program_reader = ProgramReaderStub(programs)
    curriculum_reader = CurriculumReaderStub(curricula)
    return ComparisonSummaryService(
        CompareProgramsService(program_reader, curriculum_reader, disciplines),
        program_reader,
        curriculum_reader,
    ), programs, curricula


def test_summary_preserves_requested_two_program_order_and_evidence(parsed_bundle) -> None:
    service, programs, _ = make_service(parsed_bundle)
    request = ComparisonSummaryRequest(program_ids=(programs[1].id, programs[0].id))

    result = service.summarize(request)

    assert [item.program.id for item in result.programs] == [programs[1].id, programs[0].id]
    assert result.key_differences
    assert all(difference.evidence for difference in result.key_differences)
    assert result.source_gaps == ()


def test_summary_preserves_three_programs_and_reports_missing_curriculum(parsed_bundle) -> None:
    service, programs, curricula = make_service(parsed_bundle)
    third = programs[1].model_copy(
        update={
            "id": "program:09.03.01-13",
            "code": "09.03.01-13",
        }
    )
    program_reader = ProgramReaderStub((*programs, third))
    curriculum_reader = CurriculumReaderStub(curricula[:1])
    discipline_reader = DisciplineReaderStub(parsed_bundle[1].disciplines)
    service = ComparisonSummaryService(
        CompareProgramsService(program_reader, curriculum_reader, discipline_reader),
        program_reader,
        curriculum_reader,
    )

    result = service.summarize(ComparisonSummaryRequest(program_ids=(programs[0].id, programs[1].id, third.id)))

    assert [item.program.id for item in result.programs] == [program.id for program in (*programs, third)]
    assert any(gap.code == "curriculum_missing" and third.id in gap.program_ids for gap in result.source_gaps)
    missing = next(item for item in result.programs if item.program.id == third.id)
    assert missing.totals is None
    assert missing.area_breakdown == ()


@pytest.mark.parametrize(
    "program_ids",
    [
        "program:09.03.01-02",
        "program:09.03.01-02,program:09.03.01-02",
        "program:09.03.01-02,program:09.03.01-12,program:09.03.01-13,program:09.03.01-14",
    ],
)
def test_summary_request_rejects_invalid_cardinality(program_ids: str) -> None:
    with pytest.raises(ValueError):
        ComparisonSummaryRequest.from_query(program_ids)
