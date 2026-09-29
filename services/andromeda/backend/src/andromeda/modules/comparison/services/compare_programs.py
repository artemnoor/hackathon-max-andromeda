from __future__ import annotations

import logging
from decimal import Decimal

from andromeda.modules.curricula.contracts.public import Curriculum
from andromeda.modules.curricula.repository.ports import CurriculumReader
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.disciplines.repository.ports import DisciplineReader
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.shared.contracts.enums import CompareStatus, ComparisonScope
from andromeda.shared.contracts.errors import ContractError, ErrorCode, NotFoundError
from andromeda.shared.contracts.ids import ProgramId

from ..contracts.public import ComparisonRequest, ComparisonResult
from ..contracts.results import ComparisonRow
from ..domain.alignment import ComparisonKey, align_workloads
from ..domain.entities import Workload
from .aggregation import area_distribution, totals


logger = logging.getLogger("andromeda.comparison.service")


class CompareProgramsService:
    """Compare canonical contracts through public reader ports only."""

    def __init__(self, programs: ProgramReader, curricula: CurriculumReader, disciplines: DisciplineReader) -> None:
        self._programs = programs
        self._curricula = curricula
        self._disciplines = disciplines

    def compare(self, request: ComparisonRequest) -> ComparisonResult:
        program_a = self._require_program(request.program_a_id)
        program_b = self._require_program(request.program_b_id)
        curriculum_a = self._require_curriculum(program_a.id)
        curriculum_b = self._require_curriculum(program_b.id)
        left, left_disciplines = self._workloads(curriculum_a, request)
        right, right_disciplines = self._workloads(curriculum_b, request)
        aligned = align_workloads(left, right)
        disciplines = {**left_disciplines, **right_disciplines}
        rows = tuple(
            self._row(entry.key, disciplines, entry.left, entry.right, entry.status)
            for entry in aligned
        )
        totals_a = totals(left.values())
        totals_b = totals(right.values())
        area_breakdown_a = area_distribution((left[key], left_disciplines[key]) for key in left)
        area_breakdown_b = area_distribution((right[key], right_disciplines[key]) for key in right)
        logger.info(
            "comparison_complete program_a=%s program_b=%s scope=%s rows=%d",
            program_a.id,
            program_b.id,
            request.scope.value,
            len(rows),
        )
        return ComparisonResult(
            program_a=program_a,
            program_b=program_b,
            scope=request.scope,
            semester=request.semester,
            rows=rows,
            totals_a=totals_a,
            totals_b=totals_b,
            area_breakdown_a=area_breakdown_a,
            area_breakdown_b=area_breakdown_b,
            provenance=(*program_a.provenance, *curriculum_a.provenance, *program_b.provenance, *curriculum_b.provenance),
            source_gap_details=(*program_a.source_gaps, *curriculum_a.source_gaps, *program_b.source_gaps, *curriculum_b.source_gaps),
        )

    def _require_program(self, program_id: ProgramId) -> Program:
        program = self._programs.get(program_id)
        if program is None:
            raise NotFoundError("Program was not found")
        return program

    def _require_curriculum(self, program_id: ProgramId) -> Curriculum:
        curriculum = self._curricula.get_for_program(program_id)
        if curriculum is None:
            raise NotFoundError("Curriculum was not found")
        return curriculum

    def _workloads(
        self,
        curriculum: Curriculum,
        request: ComparisonRequest,
    ) -> tuple[dict[ComparisonKey, Workload], dict[ComparisonKey, Discipline]]:
        values: dict[ComparisonKey, Workload] = {}
        disciplines: dict[ComparisonKey, Discipline] = {}
        for item in curriculum.items:
            if request.scope is ComparisonScope.SEMESTER and item.semester != request.semester:
                continue
            discipline = self._disciplines.get(item.discipline_id)
            if discipline is None:
                raise ContractError(ErrorCode.CONTRACT_ERROR, "Curriculum item discipline is missing")
            key = (discipline.normalized_name, item.semester)
            if key in values:
                raise ContractError(ErrorCode.CONTRACT_ERROR, "Duplicate comparison identity")
            values[key] = Workload(
                semester=item.semester,
                hours=item.hours,
                credits=item.credits,
                assessment_types=item.assessment_types,
            )
            disciplines[key] = discipline
        return values, disciplines

    @staticmethod
    def _row(
        key: ComparisonKey,
        disciplines: dict[ComparisonKey, Discipline],
        left: Workload | None,
        right: Workload | None,
        status: CompareStatus,
    ) -> ComparisonRow:
        discipline = disciplines.get(key)
        if discipline is None:
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Comparison discipline is missing")
        credits_delta: Decimal | None = None
        if left is not None and right is not None and left.credits is not None and right.credits is not None:
            credits_delta = left.credits - right.credits
        elif status is CompareStatus.ONLY_A and left is not None:
            credits_delta = left.credits
        elif status is CompareStatus.ONLY_B and right is not None and right.credits is not None:
            credits_delta = -right.credits
        present = left or right
        return ComparisonRow(
            discipline=discipline,
            semester=key[1],
            a=left,
            b=right,
            status=status,
            hours_delta=(left.hours if left else 0) - (right.hours if right else 0),
            credits_delta=credits_delta,
        )
