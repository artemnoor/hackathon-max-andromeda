from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.admission_fit.services.scoring import AdmissionFitScoringService
from andromeda.modules.proftest.contracts.public import ActivityCode, Confidence, ProgramFingerprint, UserProfile
from andromeda.modules.recommendations.contracts.public import RecommendationRequest
from andromeda.modules.recommendations.services.recommendations import RecommendationService

from .conftest import applicant, offering


def content_profile() -> UserProfile:
    return UserProfile(
        preferred_subject_weights={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")},
        preferred_activity_weights={ActivityCode.SOFTWARE_CREATION: Decimal("1")},
        confidence=Confidence(value=Decimal("1"), answered_base=1, answered_adaptive=0),
    )


def content_fingerprint() -> ProgramFingerprint:
    return ProgramFingerprint(
        program_id="program:09.03.01-02",
        program_code="09.03.01-02",
        program_name="Synthetic",
        basis="hours",
        total_hours=100,
        total_credits=Decimal("10"),
        total_workload=Decimal("100"),
        area_hours={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("100")},
        area_share={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")},
        semester_distribution={"1": Decimal("1")},
        activity_signals={ActivityCode.SOFTWARE_CREATION: Decimal("1")},
    )


class FingerprintReader:
    def list_fingerprints(self):
        return (content_fingerprint(),)


def test_admission_fit_has_no_effect_on_content_fit_service() -> None:
    recommendation_service = RecommendationService(FingerprintReader())
    request = RecommendationRequest(profile=content_profile(), limit=1)
    before = recommendation_service.recommend(request)
    AdmissionFitScoringService().score("program:09.03.01-02", offering(), applicant(("Математика", "90")))
    after = recommendation_service.recommend(request)

    assert before == after
