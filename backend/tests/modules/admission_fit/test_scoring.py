from __future__ import annotations

from decimal import Decimal

from andromeda.modules.admission_fit.contracts.public import AdmissionFitMetricStatus, AdmissionFitStatus
from andromeda.modules.admissions.contracts.public import (
    AdmissionCompetitionType,
    PassingScore,
    PassingScoreStatus,
    PassingScoreType,
)
from andromeda.modules.admission_fit.services.scoring import AdmissionFitScoringService

from .conftest import applicant, offering


def test_high_scores_are_realistic_and_use_real_breakdown_components() -> None:
    result = AdmissionFitScoringService().score(
        "program:09.03.01-02",
        offering(),
        applicant(("Математика", "90"), ("Русский язык", "90"), ("Физика", "90")),
    )

    assert result.status is AdmissionFitStatus.REALISTIC
    assert result.score == 100
    assert result.breakdown.minimum_readiness.value == Decimal("100.00")
    assert result.breakdown.passing_readiness.status is AdmissionFitMetricStatus.AVAILABLE
    assert result.applicant_total_score == Decimal("270")
    assert result.reasons
    assert result.anti_reasons == ()


def test_passing_score_shortfall_is_borderline_when_minimums_are_met() -> None:
    result = AdmissionFitScoringService().score(
        "program:09.03.01-02",
        offering(passing_score=Decimal("260")),
        applicant(("Математика", "80"), ("Русский язык", "80"), ("Физика", "80")),
    )

    assert result.status is AdmissionFitStatus.BORDERLINE
    assert result.breakdown.passing_readiness.value == Decimal("92.31")
    assert any("проходного" in reason.message for reason in result.anti_reasons)


def test_known_minimum_failure_is_unlikely_and_explained() -> None:
    result = AdmissionFitScoringService().score(
        "program:09.03.01-02",
        offering(),
        applicant(("Математика", "30"), ("Русский язык", "90"), ("Физика", "90")),
    )

    assert result.status is AdmissionFitStatus.UNLIKELY
    assert result.score < 100
    assert any(reason.subject == "Математика" for reason in result.anti_reasons)
    assert result.anti_reasons[0].reference_score == Decimal("46")


def test_missing_required_score_is_insufficient_data_not_zero_interest() -> None:
    result = AdmissionFitScoringService().score(
        "program:09.03.01-02",
        offering(),
        applicant(("Математика", "90")),
    )

    assert result.status is AdmissionFitStatus.INSUFFICIENT_DATA
    assert result.data_quality.value == "partial"
    assert result.breakdown.data_completeness.value == Decimal("33.33")
    assert len(result.data_gaps) == 2


def test_missing_passing_score_is_explicit_and_does_not_get_invented() -> None:
    result = AdmissionFitScoringService().score(
        "program:09.03.01-02",
        offering(passing_score=None),
        applicant(("Математика", "90"), ("Русский язык", "90"), ("Физика", "90")),
    )

    assert result.status is AdmissionFitStatus.REALISTIC
    assert result.breakdown.passing_readiness.status is AdmissionFitMetricStatus.NOT_AVAILABLE
    assert result.breakdown.passing_readiness.value is None
    assert result.data_gaps


def test_choice_exam_is_not_made_mandatory_without_a_choice_group() -> None:
    source_offering = offering()
    source_offering = source_offering.model_copy(update={"passing_scores": (source_offering.passing_scores[0].model_copy(update={"score": Decimal("160")}),)})
    source_offering = source_offering.model_copy(
        update={"exams": (source_offering.exams[0].model_copy(update={"is_choice": True}), *source_offering.exams[1:])}
    )

    result = AdmissionFitScoringService().score(
        "program:09.03.01-02",
        source_offering,
        applicant(("Русский язык", "90"), ("Физика", "90")),
    )

    assert result.breakdown.data_completeness.value == Decimal("100.00")
    assert result.status is AdmissionFitStatus.REALISTIC


def test_admission_fit_ignores_quota_and_bvi_passing_scores() -> None:
    source = offering()
    provenance = source.passing_scores[0].provenance
    quota = PassingScore(
        score_type=PassingScoreType.BUDGET,
        competition_type=AdmissionCompetitionType.TARGETED,
        score=Decimal("195"),
        provenance=provenance,
    )
    bvi = PassingScore(
        score_type=PassingScoreType.BUDGET,
        competition_type=AdmissionCompetitionType.BVI,
        status=PassingScoreStatus.BVI,
        score=None,
        provenance=provenance,
    )
    quota_only = source.model_copy(update={"passing_scores": (quota,)})
    mixed = source.model_copy(update={"passing_scores": (quota, bvi)})
    applicant_profile = applicant(("Математика", "90"), ("Русский язык", "90"), ("Физика", "90"))

    for candidate in (quota_only, mixed):
        result = AdmissionFitScoringService().score("program:09.03.01-02", candidate, applicant_profile)
        assert result.breakdown.passing_readiness.status is AdmissionFitMetricStatus.NOT_AVAILABLE
        assert result.breakdown.passing_readiness.value is None
        assert any("проходного" in gap.message for gap in result.data_gaps)
