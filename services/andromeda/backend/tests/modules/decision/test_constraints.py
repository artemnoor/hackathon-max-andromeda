from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from andromeda.modules.admissions.contracts.public import AdmissionOffering, AdmissionProvenance, AdmissionScope, FundingType, ProgramAdmissions, StudyForm, TuitionCost
from andromeda.modules.decision.contracts.public import AdmissionConstraints, DecisionConstraintApplicability, DecisionConstraintDimension
from andromeda.modules.decision.repository.ports import ProgramCandidateSnapshot
from andromeda.modules.decision.services.constraints import DecisionConstraintEvaluator
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.universities.contracts.public import University


NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
PROVENANCE = AdmissionProvenance(
    source_kind="fixture",
    source_url="https://example.test/admissions",
    captured_at=NOW,
    content_sha256="a" * 64,
)


def _snapshot(*, with_sources: bool = True) -> ProgramCandidateSnapshot:
    program = Program(
        id="program:bmstu:09.03.01-01",
        direction_id="direction:bmstu:09.03.01",
        code="09.03.01-01",
        name="Программа",
        education_year=2026,
        study_plan_url="https://example.test/plan.pdf",
        source_url="https://example.test/program",
    )
    if not with_sources:
        return ProgramCandidateSnapshot(program=program)
    admissions = ProgramAdmissions(
        program_id=program.id,
        offerings=(
            AdmissionOffering(
                id="admission-offering:program:bmstu:09.03.01-01:2026:full_time:budget",
                program_id=program.id,
                admission_year=2026,
                study_form=StudyForm.FULL_TIME,
                funding_type=FundingType.BUDGET,
                scope=AdmissionScope.PROGRAM,
                provenance=(PROVENANCE,),
            ),
            AdmissionOffering(
                id="admission-offering:program:bmstu:09.03.01-01:2026:full_time:paid",
                program_id=program.id,
                admission_year=2026,
                study_form=StudyForm.FULL_TIME,
                funding_type=FundingType.PAID,
                scope=AdmissionScope.PROGRAM,
                tuition=(
                    TuitionCost(
                        amount=Decimal("120000"),
                        currency="RUB",
                        academic_year="2026",
                        study_form=StudyForm.FULL_TIME,
                        provenance=PROVENANCE,
                    ),
                ),
                provenance=(PROVENANCE,),
            ),
        ),
    )
    university = University(
        id="university:bmstu",
        name="МГТУ",
        city="Москва",
        official_site="https://example.test",
        address="Москва",
    )
    return ProgramCandidateSnapshot(program=program, admissions=admissions, university=university)


def test_constraints_compare_offering_tuition_and_authoritative_location() -> None:
    outcomes = DecisionConstraintEvaluator().evaluate(
        _snapshot(),
        AdmissionConstraints(
            admission_year=2026,
            funding_preference=FundingType.PAID,
            study_form=StudyForm.FULL_TIME,
            max_tuition=Decimal("100000"),
            location="Москва",
        ),
        None,
    )

    by_dimension = {item.dimension: item for item in outcomes}
    assert by_dimension[DecisionConstraintDimension.ADMISSION_YEAR].satisfied is True
    assert by_dimension[DecisionConstraintDimension.FUNDING].satisfied is True
    assert by_dimension[DecisionConstraintDimension.STUDY_FORM].satisfied is True
    assert by_dimension[DecisionConstraintDimension.MAX_TUITION].satisfied is False
    assert by_dimension[DecisionConstraintDimension.LOCATION].satisfied is True
    assert all(item.applicability is DecisionConstraintApplicability.APPLIED for item in outcomes)


def test_budget_constraint_does_not_invent_a_tuition_failure() -> None:
    outcome = DecisionConstraintEvaluator().evaluate(
        _snapshot(),
        AdmissionConstraints(funding_preference=FundingType.BUDGET, max_tuition=Decimal("1")),
        None,
    )[-1]

    assert outcome.dimension is DecisionConstraintDimension.MAX_TUITION
    assert outcome.applicability is DecisionConstraintApplicability.NOT_APPLICABLE
    assert outcome.satisfied is None


def test_missing_admission_and_location_sources_are_explicitly_not_evaluated() -> None:
    outcomes = DecisionConstraintEvaluator().evaluate(
        _snapshot(with_sources=False),
        AdmissionConstraints(admission_year=2026, max_tuition=Decimal("100000"), location="Москва"),
        None,
    )

    assert all(item.applicability is DecisionConstraintApplicability.INSUFFICIENT_DATA for item in outcomes)
    assert all(item.satisfied is None for item in outcomes)
    assert all(item.source_gaps for item in outcomes)
