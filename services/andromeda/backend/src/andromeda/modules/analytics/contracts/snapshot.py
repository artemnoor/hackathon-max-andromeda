"""Canonical snapshot shape consumed by the projection builder.

The protocol keeps analytics independent from the ingestion implementation while
allowing the existing canonical snapshot to satisfy it structurally.
"""

from __future__ import annotations

from typing import Protocol

from andromeda.modules.admissions.contracts.public import ProgramAdmissions
from andromeda.modules.curricula.contracts.public import Curriculum
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program


class CanonicalAnalyticsSnapshot(Protocol):
    programs: tuple[Program, ...]
    disciplines: tuple[Discipline, ...]
    curricula: tuple[Curriculum, ...]
    admissions: tuple[ProgramAdmissions, ...]


__all__ = ["CanonicalAnalyticsSnapshot"]
