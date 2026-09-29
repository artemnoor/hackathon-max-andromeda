"""Compatibility conversion from shared analytics projections to proftest DTOs."""

from __future__ import annotations

from typing import Literal

from andromeda.modules.program_analytics.contracts.public import ProgramProjection

from .entities import ActivityCode, ProgramFingerprint


def fingerprint_from_projection(projection: ProgramProjection) -> ProgramFingerprint:
    """Keep legacy consumers working without rebuilding canonical curricula."""

    if projection.workload.basis.value not in {"hours", "credits"}:
        raise ValueError("legacy fingerprint requires an hours or credits projection basis")
    basis: Literal["hours", "credits"] = "hours" if projection.workload.basis.value == "hours" else "credits"
    total_hours = projection.workload.total_hours
    total_credits = projection.workload.total_credits
    total_workload = projection.workload.total_workload
    if total_hours is None or total_credits is None or total_workload is None:
        raise ValueError("legacy fingerprint cannot represent missing workload totals")
    activity_signals = {ActivityCode(code.value): value for code, value in projection.activity_signals.items()}
    return ProgramFingerprint(
        program_id=projection.program_id,
        program_code=projection.program_code,
        program_name=projection.program_name,
        basis=basis,
        total_hours=total_hours,
        total_credits=total_credits,
        total_workload=total_workload,
        area_hours={area: total_workload * share for area, share in projection.academic_areas.items()},
        area_share=dict(projection.academic_areas),
        semester_distribution=dict(projection.timeline.by_semester),
        activity_signals=activity_signals,
        distinctive_subjects=(),
        provenance=projection.provenance,
        source_gaps=projection.source_gaps,
    )


__all__ = ["fingerprint_from_projection"]
