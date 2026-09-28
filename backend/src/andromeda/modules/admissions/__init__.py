"""Admissions domain module public surface."""

from .contracts.public import (
    AdmissionOffering,
    AdmissionCompetitionType,
    AdmissionProvenance,
    ExamRequirement,
    FundingType,
    PassingScore,
    PassingScoreStatus,
    PassingScoreType,
    ProgramAdmissions,
    Quota,
    QuotaType,
    StudyForm,
    TuitionCost,
)
from .repository.ports import AdmissionReader, AdmissionRepository, AdmissionWriter, BatchAdmissionReader

__all__ = [
    "AdmissionOffering",
    "AdmissionCompetitionType",
    "AdmissionProvenance",
    "AdmissionReader",
    "AdmissionRepository",
    "AdmissionWriter",
    "BatchAdmissionReader",
    "ExamRequirement",
    "FundingType",
    "PassingScore",
    "PassingScoreStatus",
    "PassingScoreType",
    "ProgramAdmissions",
    "Quota",
    "QuotaType",
    "StudyForm",
    "TuitionCost",
]
