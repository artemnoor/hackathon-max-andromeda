from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.admissions.contracts.public import (
    AdmissionCompetitionType,
    AdmissionOffering,
    AdmissionProvenance,
    AdmissionScope,
    ExamRequirement,
    FundingType,
    PassingScore,
    PassingScoreStatus,
    PassingScoreType,
    ProgramAdmissions,
    StudyForm,
)

HASH = "a" * 64


def provenance() -> AdmissionProvenance:
    return AdmissionProvenance(
        source_kind="bmstu_major_detail",
        source_url="https://bmstu.ru/bachelor/majors/example",
        captured_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        content_sha256=HASH,
    )


def test_admission_contract_keeps_program_identity_and_source_values() -> None:
    source = provenance()
    offering = AdmissionOffering(
        id="admission-offering:program:09.03.01-02:2026:full_time:budget:direction",
        program_id="program:09.03.01-02",
        admission_year=2026,
        study_form=StudyForm.FULL_TIME,
        funding_type=FundingType.BUDGET,
        scope=AdmissionScope.DIRECTION,
        places=318,
        exams=(
            ExamRequirement(
                subject="Математика профильная",
                source_name="Математика профильная",
                minimum_score=Decimal("46"),
                provenance=source,
            ),
        ),
        provenance=(source,),
    )
    result = ProgramAdmissions(program_id="program:09.03.01-02", offerings=(offering,))
    assert result.offerings[0].places == 318
    assert result.offerings[0].exams[0].minimum_score == Decimal("46")


def test_program_admissions_rejects_offering_for_another_program() -> None:
    source = provenance()
    offering = AdmissionOffering(
        id="admission-offering:program:09.03.01-12:2026:full_time:budget:direction",
        program_id="program:09.03.01-12",
        admission_year=2026,
        scope=AdmissionScope.DIRECTION,
        provenance=(source,),
    )
    with pytest.raises(ValidationError, match="envelope program"):
        ProgramAdmissions(program_id="program:09.03.01-02", offerings=(offering,))


def test_contract_rejects_extra_fields_and_negative_values() -> None:
    source = provenance()
    with pytest.raises(ValidationError):
        AdmissionOffering(
            id="admission-offering:program:09.03.01-02:2026:full_time:budget:direction",
            program_id="program:09.03.01-02",
            admission_year=2026,
            places=-1,
            provenance=(source,),
            unexpected=True,
        )


def test_offering_preserves_source_defined_campus_and_exam_choice_group() -> None:
    group_id = "exam-choice:ege-third"
    exams = (
        ExamRequirement(
            subject="Физика",
            source_name="Физика",
            is_choice=True,
            choice_group_id=group_id,
            choice_group_min=1,
            choice_group_max=1,
            provenance=provenance(),
        ),
        ExamRequirement(
            subject="Информатика",
            source_name="Информатика",
            is_choice=True,
            choice_group_id=group_id,
            choice_group_min=1,
            choice_group_max=1,
            provenance=provenance(),
        ),
    )
    offering = AdmissionOffering(
        id="admission-offering:program:09.03.01-02:2026:full_time:budget:direction:campus:bmstu-kaluga",
        program_id="program:09.03.01-02",
        admission_year=2026,
        campus_id="campus:bmstu-kaluga",
        scope=AdmissionScope.DIRECTION,
        exams=exams,
        provenance=(provenance(),),
    )

    assert offering.campus_id == "campus:bmstu-kaluga"
    assert {exam.choice_group_id for exam in offering.exams} == {group_id}
    assert {exam.choice_group_max for exam in offering.exams} == {1}


def test_offering_rejects_conflicting_exam_choice_group_cardinality() -> None:
    first = ExamRequirement(
        subject="Физика",
        source_name="Физика",
        is_choice=True,
        choice_group_id="exam-choice:ege-third",
        choice_group_min=1,
        choice_group_max=1,
        provenance=provenance(),
    )
    second = first.model_copy(
        update={"subject": "Информатика", "source_name": "Информатика", "choice_group_max": 2}
    )
    with pytest.raises(ValidationError, match="inconsistent cardinality"):
        AdmissionOffering(
            id="admission-offering:program:09.03.01-02:2026:full_time:budget:direction",
            program_id="program:09.03.01-02",
            admission_year=2026,
            scope=AdmissionScope.DIRECTION,
            exams=(first, second),
            provenance=(provenance(),),
        )


def test_passing_score_defaults_preserve_legacy_numeric_payloads() -> None:
    value = PassingScore(score_type=PassingScoreType.BUDGET, score=Decimal("247"), provenance=provenance())

    assert value.competition_type is AdmissionCompetitionType.GENERAL
    assert value.status is PassingScoreStatus.NUMERIC
    assert PassingScore.model_validate_json(value.model_dump_json(), strict=False) == value


def test_passing_score_represents_quota_numeric_and_bvi_facts_without_zero_sentinel() -> None:
    numeric = PassingScore(
        score_type=PassingScoreType.BUDGET,
        competition_type=AdmissionCompetitionType.TARGETED,
        score=Decimal("195"),
        provenance=provenance(),
    )
    bvi = PassingScore(
        score_type=PassingScoreType.BUDGET,
        competition_type=AdmissionCompetitionType.SEPARATE_QUOTA,
        status=PassingScoreStatus.BVI,
        score=None,
        provenance=provenance(),
    )

    assert numeric.score == Decimal("195")
    assert bvi.score is None
    assert bvi.status is PassingScoreStatus.BVI


@pytest.mark.parametrize(
    "kwargs",
    (
        {"status": PassingScoreStatus.NUMERIC, "score": None},
        {"status": PassingScoreStatus.BVI, "score": Decimal("0"), "competition_type": AdmissionCompetitionType.BVI},
        {"status": PassingScoreStatus.BVI, "score": None, "competition_type": AdmissionCompetitionType.GENERAL},
    ),
)
def test_passing_score_rejects_invalid_status_score_combinations(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PassingScore(score_type=PassingScoreType.BUDGET, provenance=provenance(), **kwargs)
