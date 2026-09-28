"""Exact comparison of approved policy snapshots across admission cycles."""

from __future__ import annotations

from pydantic import model_validator

from andromeda.shared.contracts.base import ContractModel

from .resolution import ResolutionTrace
from .semantic_diff import PolicySemanticDiff


class PolicyCycleComparison(ContractModel):
    before_trace: ResolutionTrace
    after_trace: ResolutionTrace
    diff: PolicySemanticDiff

    @model_validator(mode="after")
    def traces_match_diff(self) -> PolicyCycleComparison:
        before = self.before_trace
        after = self.after_trace
        if before.admission_year >= after.admission_year:
            raise ValueError("policy cycle comparison must be chronological")
        if before.university_id != after.university_id:
            raise ValueError("policy cycle comparison must use one university")
        if before.as_known_at != after.as_known_at:
            raise ValueError(
                "policy cycle comparison must use one knowledge-time cutoff"
            )
        if (
            self.diff.before_trace_id != before.trace_id
            or self.diff.after_trace_id != after.trace_id
        ):
            raise ValueError("policy cycle diff must reference both exact traces")
        return self


__all__ = ["PolicyCycleComparison"]
