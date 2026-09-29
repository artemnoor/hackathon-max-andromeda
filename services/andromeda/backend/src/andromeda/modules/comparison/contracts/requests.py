from __future__ import annotations

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from ....shared.contracts.base import ContractModel
from ....shared.contracts.enums import ComparisonScope
from ....shared.contracts.ids import ProgramId, Semester


class ComparisonRequest(ContractModel):
    program_a_id: ProgramId
    program_b_id: ProgramId
    scope: ComparisonScope = ComparisonScope.ALL
    semester: Semester | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> ComparisonRequest:
        if self.program_a_id == self.program_b_id:
            raise ValueError("comparison requires two distinct programs")
        if self.scope is ComparisonScope.SEMESTER and self.semester is None:
            raise ValueError("semester is required for semester scope")
        if self.scope is ComparisonScope.ALL and self.semester is not None:
            raise ValueError("semester is only allowed for semester scope")
        return self

    @classmethod
    def from_query(cls, program_ids: str, *, scope: str = "all", semester: int | None = None) -> ComparisonRequest:
        parts = tuple(part.strip() for part in program_ids.split(","))
        if len(parts) != 2 or parts[0] == parts[1]:
            raise ValueError("programIds must contain exactly two distinct program ids")
        adapter = TypeAdapter(ProgramId)
        try:
            left, right = adapter.validate_python(parts[0]), adapter.validate_python(parts[1])
            selected_scope = ComparisonScope(scope)
        except (ValidationError, ValueError) as exc:
            raise ValueError("programIds and scope must satisfy the comparison contract") from exc
        return cls(program_a_id=left, program_b_id=right, scope=selected_scope, semester=semester)


class ComparisonSummaryRequest(ContractModel):
    """Bounded request for the additive summary of two or three programs."""

    program_ids: tuple[ProgramId, ...] = Field(min_length=2, max_length=3)
    scope: ComparisonScope = ComparisonScope.ALL
    semester: Semester | None = None

    @model_validator(mode="after")
    def validate_request(self) -> ComparisonSummaryRequest:
        if len(set(self.program_ids)) != len(self.program_ids):
            raise ValueError("comparison summary requires distinct programs")
        if self.scope is ComparisonScope.SEMESTER and self.semester is None:
            raise ValueError("semester is required for semester scope")
        if self.scope is ComparisonScope.ALL and self.semester is not None:
            raise ValueError("semester is only allowed for semester scope")
        return self

    @classmethod
    def from_query(
        cls,
        program_ids: str,
        *,
        scope: str = "all",
        semester: int | None = None,
    ) -> ComparisonSummaryRequest:
        parts = tuple(part.strip() for part in program_ids.split(",") if part.strip())
        if len(parts) < 2 or len(parts) > 3 or len(set(parts)) != len(parts):
            raise ValueError("programIds must contain two or three distinct program ids")
        adapter = TypeAdapter(ProgramId)
        try:
            selected = tuple(adapter.validate_python(part) for part in parts)
            selected_scope = ComparisonScope(scope)
        except (ValidationError, ValueError) as exc:
            raise ValueError("programIds and scope must satisfy the comparison summary contract") from exc
        return cls(program_ids=selected, scope=selected_scope, semester=semester)
