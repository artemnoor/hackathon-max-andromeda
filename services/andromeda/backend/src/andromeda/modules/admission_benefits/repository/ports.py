"""Typed repository ports for source-backed admission-benefit facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from andromeda.shared.contracts.enums import EducationLevel
from andromeda.shared.contracts.ids import (
    AdmissionCampusId,
    DirectionCode,
    EducationYear,
    IngestRunId,
    OlympiadId,
    ProgramId,
    UniversityId,
)

from ..contracts.public import (
    AdmissionBenefitRule,
    IndividualAchievementPolicy,
    Olympiad,
)
from ..contracts.snapshot import AdmissionBenefitsSnapshot


@dataclass(frozen=True, slots=True)
class AdmissionBenefitSyncStats:
    olympiads_inserted: int = 0
    profiles_inserted: int = 0
    rules_inserted: int = 0
    achievement_rules_inserted: int = 0
    stale_rows: int = 0
    unchanged_rows: int = 0
    conflict_rows: int = 0


class AdmissionBenefitReader(Protocol):
    def get_catalog(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        education_level: EducationLevel | None = None,
    ) -> AdmissionBenefitsSnapshot | None: ...

    def get_rules_for_program(
        self,
        program_id: ProgramId,
        admission_year: EducationYear,
        *,
        include_review: bool = False,
        campus_id: AdmissionCampusId | None = None,
    ) -> tuple[AdmissionBenefitRule, ...]: ...

    def get_rules_for_direction(
        self,
        direction_code: DirectionCode,
        university_id: UniversityId,
        admission_year: EducationYear,
        *,
        education_level: EducationLevel | None = None,
        include_review: bool = False,
        campus_id: AdmissionCampusId | None = None,
    ) -> tuple[AdmissionBenefitRule, ...]: ...

    def get_programs_for_olympiad(
        self,
        olympiad_id: OlympiadId,
        university_id: UniversityId,
        admission_year: EducationYear,
        *,
        benefit_type: str | None = None,
        include_review: bool = False,
    ) -> tuple[AdmissionBenefitRule, ...]: ...

    def get_olympiad_catalog(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
    ) -> tuple[Olympiad, ...]: ...

    def get_individual_achievement_policy(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        education_level: EducationLevel | None = None,
        *,
        include_review: bool = False,
    ) -> IndividualAchievementPolicy | None: ...

    def get_rule_revision(
        self, rule_id: str, revision_hash: str
    ) -> AdmissionBenefitRule | None: ...

    def get_individual_achievement_policy_revision(
        self, policy_id: str, revision_hash: str
    ) -> IndividualAchievementPolicy | None: ...


class AdmissionBenefitWriter(Protocol):
    def sync_snapshot(
        self,
        snapshot: AdmissionBenefitsSnapshot,
        *,
        source_run_id: IngestRunId,
    ) -> AdmissionBenefitSyncStats: ...

    def mark_stale_for_source_revision(
        self,
        *,
        university_id: UniversityId,
        admission_year: EducationYear,
        source_kind: str,
        source_url: str,
        current_hash: str,
    ) -> int: ...


class AdmissionBenefitRepository(AdmissionBenefitReader, AdmissionBenefitWriter, Protocol):
    """Combined port used by application composition and ingestion infrastructure."""


__all__ = [
    "AdmissionBenefitReader",
    "AdmissionBenefitRepository",
    "AdmissionBenefitSyncStats",
    "AdmissionBenefitWriter",
]
