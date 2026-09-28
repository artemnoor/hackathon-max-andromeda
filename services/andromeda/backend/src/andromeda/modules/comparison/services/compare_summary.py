from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from itertools import combinations
import logging

from andromeda.modules.curricula.repository.ports import CurriculumReader
from andromeda.modules.disciplines.contracts.public import DisciplineAreaSummary, area_definition
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.programs.repository.ports import ProgramReader
from andromeda.shared.contracts.enums import CompareStatus, ComparisonScope
from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.ids import ProgramId

from ..contracts.public import ComparisonRequest, ComparisonSummaryRequest, ComparisonSummaryResult
from ..contracts.results import (
    ComparisonEvidence,
    ComparisonDifferenceDirection,
    ComparisonResult,
    ComparisonSourceGap,
    ComparisonTotals,
    KeyDifference,
    ProgramComparisonOverview,
    Tradeoff,
)
from ..services.ports import ComparisonService


logger = logging.getLogger("andromeda.comparison.summary")


class ComparisonSummaryService:
    """Build a deterministic summary from the existing raw comparison service."""

    def __init__(self, comparer: ComparisonService, programs: ProgramReader, curricula: CurriculumReader) -> None:
        self._comparer = comparer
        self._programs = programs
        self._curricula = curricula

    def summarize(self, request: ComparisonSummaryRequest) -> ComparisonSummaryResult:
        programs = tuple(self._require_program(program_id) for program_id in request.program_ids)
        source_gaps = self._curriculum_gaps(programs)
        missing_ids = {program_id for gap in source_gaps for program_id in gap.program_ids}
        pair_results: list[ComparisonResult] = []
        for left, right in combinations(programs, 2):
            if left.id in missing_ids or right.id in missing_ids:
                continue
            pair_results.append(
                self._comparer.compare(
                    ComparisonRequest(
                        program_a_id=left.id,
                        program_b_id=right.id,
                        scope=request.scope,
                        semester=request.semester,
                    )
                )
            )

        totals_by_program: dict[ProgramId, ComparisonTotals] = {}
        areas_by_program: dict[ProgramId, tuple[DisciplineAreaSummary, ...]] = {}
        differences: list[KeyDifference] = []
        tradeoffs: list[Tradeoff] = []
        for result in pair_results:
            totals_by_program[result.program_a.id] = result.totals_a
            totals_by_program[result.program_b.id] = result.totals_b
            areas_by_program[result.program_a.id] = result.area_breakdown_a
            areas_by_program[result.program_b.id] = result.area_breakdown_b
            pair_differences = self._differences(result)
            differences.extend(pair_differences)
            tradeoffs.extend(self._tradeoffs(result, pair_differences))

        overviews = tuple(
            ProgramComparisonOverview(
                program=program,
                totals=totals_by_program.get(program.id),
                area_breakdown=areas_by_program.get(program.id, ()),
                source_gaps=tuple(gap for gap in source_gaps if program.id in gap.program_ids),
            )
            for program in programs
        )
        logger.info(
            "comparison_summary_complete program_count=%d pair_count=%d difference_count=%d gap_count=%d",
            len(programs),
            len(pair_results),
            len(differences),
            len(source_gaps),
        )
        return ComparisonSummaryResult(
            programs=overviews,
            scope=request.scope,
            semester=request.semester,
            key_differences=tuple(differences),
            tradeoffs=tuple(tradeoffs),
            source_gaps=tuple(source_gaps),
        )

    def _require_program(self, program_id: ProgramId) -> Program:
        program = self._programs.get(program_id)
        if program is None:
            raise NotFoundError("Program was not found")
        return program

    def _curriculum_gaps(self, programs: Iterable[Program]) -> tuple[ComparisonSourceGap, ...]:
        gaps: list[ComparisonSourceGap] = []
        for program in programs:
            if self._curricula.get_for_program(program.id) is None:
                gaps.append(
                    ComparisonSourceGap(
                        code="curriculum_missing",
                        message=f"Учебный план программы {program.code} недоступен в текущем источнике.",
                        program_ids=(program.id,),
                        explanation="На официальной странице программы не опубликован доступный учебный план.",
                        impact="Часы, ЗЕТ и содержание этой программы нельзя корректно сопоставить.",
                        source_url=str(program.study_plan_url),
                        suggested_action="Проверьте страницу учебного плана позже; программу всё равно можно оставить в shortlist.",
                    )
                )
        return tuple(gaps)

    @staticmethod
    def _differences(result: ComparisonResult) -> tuple[KeyDifference, ...]:
        differences: list[KeyDifference] = []
        hours_delta = result.totals_a.hours - result.totals_b.hours
        if hours_delta:
            differences.append(
                KeyDifference(
                    program_a_id=result.program_a.id,
                    program_b_id=result.program_b.id,
                    dimension="workload",
                    label="Общий объём часов",
                    direction=_direction(hours_delta),
                    value_a=str(result.totals_a.hours),
                    value_b=str(result.totals_b.hours),
                    evidence=(ComparisonEvidence(kind="totals", key="hours"),),
                )
            )
        credits_delta = result.totals_a.credits - result.totals_b.credits
        if credits_delta:
            differences.append(
                KeyDifference(
                    program_a_id=result.program_a.id,
                    program_b_id=result.program_b.id,
                    dimension="credits",
                    label="Объём ЗЕТ",
                    direction=_direction(credits_delta),
                    value_a=str(result.totals_a.credits),
                    value_b=str(result.totals_b.credits),
                    evidence=(ComparisonEvidence(kind="totals", key="credits"),),
                )
            )

        area_a = {item.area: item.share for item in result.area_breakdown_a}
        area_b = {item.area: item.share for item in result.area_breakdown_b}
        area_rows = []
        for area in set(area_a) | set(area_b):
            delta = area_a.get(area, Decimal("0")) - area_b.get(area, Decimal("0"))
            if delta:
                area_rows.append((abs(delta), area, delta))
        for _, area, delta in sorted(area_rows, key=lambda item: (-item[0], item[1].value))[:8]:
            definition = area_definition(area)
            differences.append(
                KeyDifference(
                    program_a_id=result.program_a.id,
                    program_b_id=result.program_b.id,
                    dimension="area",
                    label=definition.name,
                    direction=_direction(delta),
                    value_a=str(area_a.get(area, Decimal("0"))),
                    value_b=str(area_b.get(area, Decimal("0"))),
                    evidence=(ComparisonEvidence(kind="area", key=area.value),),
                )
            )

        row_candidates = []
        for row in result.rows:
            credits_delta = row.credits_delta or Decimal("0")
            if row.status is CompareStatus.BOTH and row.hours_delta == 0 and credits_delta == 0:
                continue
            magnitude = max(Decimal(abs(row.hours_delta or 0)), abs(credits_delta))
            row_candidates.append((magnitude, row.discipline.name, row))
        for _, _, row in sorted(row_candidates, key=lambda item: (-item[0], item[1], item[2].semester or 0))[:8]:
            row_delta: int | Decimal = row.hours_delta if row.hours_delta is not None else 0
            if row_delta == 0 and row.credits_delta is not None:
                row_delta = row.credits_delta
            value_a = str(row.a.hours) if row.a is not None else None
            value_b = str(row.b.hours) if row.b is not None else None
            key = f"{row.discipline.normalized_name}:{row.semester if row.semester is not None else 'unassigned'}"
            label = row.discipline.name
            if row.semester is not None:
                label = f"{label} · семестр {row.semester}"
            differences.append(
                KeyDifference(
                    program_a_id=result.program_a.id,
                    program_b_id=result.program_b.id,
                    dimension="discipline",
                    label=label,
                    direction=_direction(row_delta),
                    value_a=value_a,
                    value_b=value_b,
                    evidence=(ComparisonEvidence(kind="discipline", key=key),),
                )
            )
        return tuple(differences)

    @staticmethod
    def _tradeoffs(result: ComparisonResult, differences: Iterable[KeyDifference]) -> tuple[Tradeoff, ...]:
        candidates = tuple(
            difference
            for difference in differences
            if difference.dimension in {"area", "discipline"}
            and difference.direction in {"more_in_a", "more_in_b"}
        )[:3]
        tradeoffs: list[Tradeoff] = []
        for difference in candidates:
            if difference.direction == "more_in_a":
                tradeoffs.extend(
                    (
                        Tradeoff(
                            program_id=result.program_a.id,
                            paired_program_id=result.program_b.id,
                            advantage=f"Больше: {difference.label} ({difference.value_a} против {difference.value_b}).",
                            consideration=f"По этой составляющей программа {result.program_b.code} даёт меньший объём.",
                            evidence=difference.evidence,
                        ),
                        Tradeoff(
                            program_id=result.program_b.id,
                            paired_program_id=result.program_a.id,
                            advantage=f"Меньше нагрузки по блоку «{difference.label}» ({difference.value_b} против {difference.value_a}).",
                            consideration=f"В программе {result.program_a.code} этот блок представлен сильнее.",
                            evidence=difference.evidence,
                        ),
                    )
                )
            else:
                tradeoffs.extend(
                    (
                        Tradeoff(
                            program_id=result.program_b.id,
                            paired_program_id=result.program_a.id,
                            advantage=f"Больше: {difference.label} ({difference.value_b} против {difference.value_a}).",
                            consideration=f"По этой составляющей программа {result.program_a.code} даёт меньший объём.",
                            evidence=difference.evidence,
                        ),
                        Tradeoff(
                            program_id=result.program_a.id,
                            paired_program_id=result.program_b.id,
                            advantage=f"Меньше нагрузки по блоку «{difference.label}» ({difference.value_a} против {difference.value_b}).",
                            consideration=f"В программе {result.program_b.code} этот блок представлен сильнее.",
                            evidence=difference.evidence,
                        ),
                    )
                )
        return tuple(tradeoffs)


def _direction(delta: int | Decimal) -> ComparisonDifferenceDirection:
    if delta > 0:
        return "more_in_a"
    if delta < 0:
        return "more_in_b"
    return "different"


__all__ = ["ComparisonSummaryService"]
