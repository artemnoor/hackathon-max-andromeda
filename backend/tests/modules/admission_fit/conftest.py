from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from andromeda.modules.admission_fit.contracts.public import ApplicantAdmissionProfile, ApplicantSubjectScore
from andromeda.modules.admissions.contracts.public import (
    AdmissionOffering,
    AdmissionProvenance,
    AdmissionScope,
    ExamRequirement,
    FundingType,
    PassingScore,
    PassingScoreType,
)
from andromeda.modules.programs.contracts.public import Program


def provenance(source_name: str = "Synthetic admissions") -> AdmissionProvenance:
    return AdmissionProvenance(
        source_kind="fixture",
        source_url="https://example.test/admissions",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_sha256="a" * 64,
        source_name=source_name,
    )


def program(program_id: str = "program:09.03.01-02") -> Program:
    code = program_id.removeprefix("program:")
    return Program(
        id=program_id,
        direction_id="direction:09.03.01",
        code=code,
        name="Synthetic program",
        education_year=2025,
        study_plan_url="https://example.test/plan.pdf",
        source_url="https://example.test/program",
    )


def offering(
    *,
    program_id: str = "program:09.03.01-02",
    minimums: tuple[Decimal | None, ...] = (Decimal("46"), Decimal("40"), Decimal("45")),
    passing_score: Decimal | None = Decimal("220"),
    funding_type: FundingType = FundingType.BUDGET,
) -> AdmissionOffering:
    source = provenance()
    subjects = ("Математика", "Русский язык", "Физика")
    exams = tuple(
        ExamRequirement(
            subject=subject,
            source_name="ЕГЭ",
            minimum_score=minimum,
            is_required=True,
            provenance=source,
        )
        for subject, minimum in zip(subjects, minimums, strict=True)
    )
    passing_scores = (
        (PassingScore(score_type=PassingScoreType.BUDGET, score=passing_score, provenance=source),)
        if passing_score is not None
        else ()
    )
    return AdmissionOffering(
        id=f"admission-offering:{program_id}:2026:full_time:{funding_type.value}:program",
        program_id=program_id,
        admission_year=2026,
        study_form=None,
        funding_type=funding_type,
        scope=AdmissionScope.PROGRAM,
        exams=exams,
        passing_scores=passing_scores,
        provenance=(source,),
    )


def applicant(*scores: tuple[str, str]) -> ApplicantAdmissionProfile:
    return ApplicantAdmissionProfile(
        scores=tuple(ApplicantSubjectScore(subject=subject, score=Decimal(score)) for subject, score in scores)
    )
