from __future__ import annotations

from decimal import Decimal

from andromeda.modules.admission_fit.contracts.public import AdmissionFitStatus
from andromeda.modules.admission_fit.services.scoring import AdmissionFitScoringService

from .conftest import applicant, offering


def evaluate(profile):
    return AdmissionFitScoringService().score("program:09.03.01-02", offering(), profile)


def test_five_synthetic_admission_personas_have_logical_outcomes() -> None:
    strong = evaluate(applicant(("Математика", "95"), ("Русский язык", "90"), ("Физика", "95")))
    borderline = evaluate(
        applicant(("Математика", "70"), ("Русский язык", "70"), ("Физика", "70"))
    )
    below_minimum = evaluate(
        applicant(("Математика", "30"), ("Русский язык", "90"), ("Физика", "90"))
    )
    missing = evaluate(applicant(("Математика", "90")))
    no_published_passing = AdmissionFitScoringService().score(
        "program:09.03.01-02",
        offering(passing_score=None),
        applicant(("Математика", "90"), ("Русский язык", "90"), ("Физика", "90")),
    )

    assert strong.status is AdmissionFitStatus.REALISTIC
    assert borderline.status is AdmissionFitStatus.BORDERLINE
    assert below_minimum.status is AdmissionFitStatus.UNLIKELY
    assert missing.status is AdmissionFitStatus.INSUFFICIENT_DATA
    assert no_published_passing.status is AdmissionFitStatus.REALISTIC


def test_identical_inputs_are_deterministic_and_score_is_monotonic() -> None:
    profile = applicant(("Математика", "80"), ("Русский язык", "80"), ("Физика", "80"))
    same_a = evaluate(profile)
    same_b = evaluate(profile)
    stronger = evaluate(applicant(("Математика", "90"), ("Русский язык", "90"), ("Физика", "90")))

    assert same_a == same_b
    assert stronger.score >= same_a.score
    assert stronger.status in {AdmissionFitStatus.REALISTIC, AdmissionFitStatus.BORDERLINE}


def test_more_severe_minimum_failure_cannot_improve_fit() -> None:
    mild = evaluate(applicant(("Математика", "45"), ("Русский язык", "90"), ("Физика", "90")))
    severe = evaluate(applicant(("Математика", "20"), ("Русский язык", "90"), ("Физика", "90")))

    assert severe.score <= mild.score
    assert severe.status is AdmissionFitStatus.UNLIKELY
