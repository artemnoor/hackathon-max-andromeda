from __future__ import annotations

from typing import Annotated, Self

from fastapi import Query
from fastapi.exceptions import RequestValidationError
from pydantic import Field, StringConstraints, TypeAdapter, ValidationError, model_validator

from andromeda.modules.comparison.contracts.public import ComparisonRequest, ComparisonResult, ComparisonSummaryRequest, ComparisonSummaryResult
from andromeda.modules.comparison.contracts.results import ComparisonSourceGap, KeyDifference, Tradeoff
from andromeda.shared.contracts.enums import ComparisonScope
from andromeda.shared.contracts.ids import ProgramId, Semester

from .common import ApiModel, ComparisonResponse, ComparisonTotalsResponse, ProgramSummaryResponse, DisciplineAreaSummaryResponse, SourceAttributionResponse, SourceGapReferenceResponse
from .disciplines import area_summary_response, discipline_response


ProgramIdsQuery = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class CompareQuery(ApiModel):
    program_ids: ProgramIdsQuery = Field(alias="programIds")
    scope: ComparisonScope = ComparisonScope.ALL
    semester: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        self.to_request()
        return self

    def to_request(self) -> ComparisonRequest:
        parts = tuple(part.strip() for part in self.program_ids.split(","))
        if len(parts) != 2 or parts[0] == parts[1]:
            raise ValueError("programIds must contain exactly two distinct program ids")
        adapter = TypeAdapter(ProgramId)
        left, right = adapter.validate_python(parts[0]), adapter.validate_python(parts[1])
        return ComparisonRequest(program_a_id=left, program_b_id=right, scope=self.scope, semester=self.semester)


class CompareSummaryQuery(ApiModel):
    program_ids: Annotated[str, StringConstraints(min_length=1, max_length=768)] = Field(alias="programIds")
    scope: ComparisonScope = ComparisonScope.ALL
    semester: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        self.to_request()
        return self

    def to_request(self) -> ComparisonSummaryRequest:
        parts = tuple(part.strip() for part in self.program_ids.split(",") if part.strip())
        if len(parts) < 2 or len(parts) > 3 or len(set(parts)) != len(parts):
            raise ValueError("programIds must contain two or three distinct program ids")
        adapter = TypeAdapter(ProgramId)
        selected = tuple(adapter.validate_python(part) for part in parts)
        return ComparisonSummaryRequest(program_ids=selected, scope=self.scope, semester=self.semester)


def parse_compare_query(
    program_ids: ProgramIdsQuery = Query(..., alias="programIds"),
    scope: ComparisonScope = Query(ComparisonScope.ALL),
    semester: int | None = Query(default=None, ge=1, le=12),
) -> CompareQuery:
    try:
        return CompareQuery(programIds=program_ids, scope=scope, semester=semester)
    except ValidationError as exc:
        errors = [{**error, "loc": ("query", *error.get("loc", ()))} for error in exc.errors()]
        raise RequestValidationError(errors) from exc


def parse_compare_summary_query(
    program_ids: Annotated[str, StringConstraints(min_length=1, max_length=768)] = Query(..., alias="programIds"),
    scope: ComparisonScope = Query(ComparisonScope.ALL),
    semester: int | None = Query(default=None, ge=1, le=12),
) -> CompareSummaryQuery:
    try:
        return CompareSummaryQuery(programIds=program_ids, scope=scope, semester=semester)
    except (ValidationError, ValueError) as exc:
        errors = [{**error, "loc": ("query", *error.get("loc", ()))} for error in (exc.errors() if isinstance(exc, ValidationError) else [{"loc": ("programIds",), "msg": str(exc), "type": "value_error"}])]
        raise RequestValidationError(errors) from exc


def comparison_response(result: ComparisonResult) -> ComparisonResponse:
    return ComparisonResponse.model_validate(
        {
            "program_a": result.program_a.model_dump(),
            "program_b": result.program_b.model_dump(),
            "scope": result.scope,
            "semester": result.semester,
            "rows": tuple(
                {
                    **row.model_dump(),
                    "discipline": discipline_response(row.discipline),
                }
                for row in result.rows
            ),
            "totals_a": result.totals_a.model_dump(),
            "totals_b": result.totals_b.model_dump(),
            "area_breakdown_a": tuple(area_summary_response(item.area, item.share) for item in result.area_breakdown_a),
            "area_breakdown_b": tuple(area_summary_response(item.area, item.share) for item in result.area_breakdown_b),
            "provenance": tuple(SourceAttributionResponse.model_validate(item.model_dump()) for item in result.provenance),
            "source_gap_details": tuple(SourceGapReferenceResponse.model_validate(item.model_dump()) for item in result.source_gap_details),
        }
    )


class ComparisonEvidenceResponse(ApiModel):
    kind: str
    key: str


class ComparisonSourceGapResponse(ApiModel):
    code: str
    message: str
    program_ids: tuple[str, ...]
    explanation: str = "Официальный источник не содержит это поле в текущем срезе."
    impact: str = "Сравнение продолжается, но этот блок нельзя считать полным."
    source_url: str | None = None
    can_continue: bool = True
    suggested_action: str = "Откройте официальный источник и проверьте обновление данных."


class ComparisonProgramOverviewResponse(ApiModel):
    program: ProgramSummaryResponse
    totals: ComparisonTotalsResponse | None = None
    area_breakdown: tuple[DisciplineAreaSummaryResponse, ...] = ()
    source_gaps: tuple[ComparisonSourceGapResponse, ...] = ()


class KeyDifferenceResponse(ApiModel):
    program_a_id: str
    program_b_id: str
    dimension: str
    label: str
    direction: str
    value_a: str | None = None
    value_b: str | None = None
    evidence: tuple[ComparisonEvidenceResponse, ...] = ()


class TradeoffResponse(ApiModel):
    program_id: str
    paired_program_id: str
    advantage: str
    consideration: str
    evidence: tuple[ComparisonEvidenceResponse, ...] = ()


class ComparisonSummaryResponse(ApiModel):
    programs: tuple[ComparisonProgramOverviewResponse, ...]
    scope: ComparisonScope
    semester: int | None = None
    key_differences: tuple[KeyDifferenceResponse, ...] = ()
    tradeoffs: tuple[TradeoffResponse, ...] = ()
    source_gaps: tuple[ComparisonSourceGapResponse, ...] = ()


def comparison_summary_response(result: ComparisonSummaryResult) -> ComparisonSummaryResponse:
    def gap_response(gap: ComparisonSourceGap) -> dict[str, object]:
        return gap.model_dump()

    def difference_response(difference: KeyDifference) -> dict[str, object]:
        return difference.model_dump()

    def tradeoff_response(tradeoff: Tradeoff) -> dict[str, object]:
        return tradeoff.model_dump()

    return ComparisonSummaryResponse.model_validate(
        {
            "programs": tuple(
                {
                    "program": overview.program.model_dump(),
                    "totals": overview.totals.model_dump() if overview.totals is not None else None,
                    "area_breakdown": tuple(area_summary_response(item.area, item.share) for item in overview.area_breakdown),
                    "source_gaps": tuple(gap_response(gap) for gap in overview.source_gaps),
                }
                for overview in result.programs
            ),
            "scope": result.scope,
            "semester": result.semester,
            "key_differences": tuple(difference_response(item) for item in result.key_differences),
            "tradeoffs": tuple(tradeoff_response(item) for item in result.tradeoffs),
            "source_gaps": tuple(gap_response(item) for item in result.source_gaps),
        }
    )
