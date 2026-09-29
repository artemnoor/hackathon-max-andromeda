from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.disciplines.contracts.public import DisciplineAreaSummary
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.enums import CompareStatus, ComparisonScope
from andromeda.shared.contracts.ids import ProgramId, Semester
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference
from ..domain.entities import Workload


class ComparisonRow(ContractModel):
    discipline: Discipline
    semester: Semester | None = None
    a: Workload | None = None
    b: Workload | None = None
    status: CompareStatus
    hours_delta: int | None = None
    credits_delta: Decimal | None = None


class ComparisonTotals(ContractModel):
    hours: int = Field(strict=True, ge=0, le=100_000)
    credits: Decimal = Field(strict=True, ge=Decimal("0"), max_digits=10, decimal_places=2)


class ComparisonResult(ContractModel):
    program_a: Program
    program_b: Program
    scope: ComparisonScope
    semester: Semester | None = None
    rows: tuple[ComparisonRow, ...]
    totals_a: ComparisonTotals
    totals_b: ComparisonTotals
    area_breakdown_a: tuple[DisciplineAreaSummary, ...] = ()
    area_breakdown_b: tuple[DisciplineAreaSummary, ...] = ()
    provenance: tuple[SourceAttribution, ...] = ()
    source_gap_details: tuple[SourceGapReference, ...] = ()


ComparisonDifferenceDirection = Literal["more_in_a", "more_in_b", "different", "unknown"]
ComparisonDifferenceDimension = Literal["area", "discipline", "workload", "credits"]


class ComparisonEvidence(ContractModel):
    """Stable pointer from a prose claim to raw comparison evidence."""

    kind: Literal["area", "discipline", "totals"]
    key: str


class ComparisonSourceGap(ContractModel):
    code: str
    message: str
    program_ids: tuple[ProgramId, ...] = ()
    explanation: str = "Официальный источник не содержит это поле в текущем срезе."
    impact: str = "Сравнение продолжается, но этот блок нельзя считать полным."
    source_url: str | None = None
    can_continue: bool = True
    suggested_action: str = "Откройте официальный источник и проверьте обновление данных."


class ProgramComparisonOverview(ContractModel):
    program: Program
    totals: ComparisonTotals | None = None
    area_breakdown: tuple[DisciplineAreaSummary, ...] = ()
    source_gaps: tuple[ComparisonSourceGap, ...] = ()


class KeyDifference(ContractModel):
    program_a_id: ProgramId
    program_b_id: ProgramId
    dimension: ComparisonDifferenceDimension
    label: str
    direction: ComparisonDifferenceDirection
    value_a: str | None = None
    value_b: str | None = None
    evidence: tuple[ComparisonEvidence, ...] = ()


class Tradeoff(ContractModel):
    program_id: ProgramId
    paired_program_id: ProgramId
    advantage: str
    consideration: str
    evidence: tuple[ComparisonEvidence, ...] = ()


class ComparisonSummaryResult(ContractModel):
    """Summary-first projection; it deliberately has no winner or global score."""

    programs: tuple[ProgramComparisonOverview, ...]
    scope: ComparisonScope
    semester: Semester | None = None
    key_differences: tuple[KeyDifference, ...] = ()
    tradeoffs: tuple[Tradeoff, ...] = ()
    source_gaps: tuple[ComparisonSourceGap, ...] = ()


__all__ = [
    "ComparisonDifferenceDirection",
    "ComparisonEvidence",
    "ComparisonResult",
    "ComparisonRow",
    "ComparisonSourceGap",
    "ComparisonSummaryResult",
    "ComparisonTotals",
    "KeyDifference",
    "ProgramComparisonOverview",
    "Tradeoff",
]
