from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.recommendations.contracts.public import ActivityCode, RecommendationRequest
from andromeda.modules.recommendations.services.recommendations import RecommendationService
from .factories import fingerprint_from_areas, profile


class _Reader:
    def __init__(self, fingerprints: tuple[object, ...]) -> None:
        self.fingerprints = fingerprints

    def list_fingerprints(self):
        return self.fingerprints


def _service() -> tuple[RecommendationService, dict[str, object]]:
    it = fingerprint_from_areas("09.03.01-02", {DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.8"), DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.2")}, {ActivityCode.SOFTWARE_CREATION: Decimal("1")})
    engineering = fingerprint_from_areas("09.03.01-12", {DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("0.7"), DisciplineAreaCode.ENGINEERING_TECHNOLOGY: Decimal("0.3")}, {ActivityCode.PHYSICAL_ENGINEERING: Decimal("1")})
    economics = fingerprint_from_areas("38.03.01-01", {DisciplineAreaCode.ECONOMICS_FINANCE: Decimal("0.7"), DisciplineAreaCode.BUSINESS_MANAGEMENT: Decimal("0.3")}, {ActivityCode.BUSINESS: Decimal("1")})
    data = fingerprint_from_areas("09.03.01-32", {DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.6"), DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.4")}, {ActivityCode.DATA: Decimal("1")})
    reader = _Reader((it, engineering, economics, data))
    return RecommendationService(reader), {"it": it, "engineering": engineering, "economics": economics, "data": data}


def _top_code(service: RecommendationService, persona) -> str:
    result = service.recommend(RecommendationRequest(profile=persona, limit=4))
    assert result.recommendations
    return result.recommendations[0].program_code


def test_synthetic_personas_preserve_content_direction_properties() -> None:
    service, programs = _service()
    it_profile = profile(subject={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.7"), DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.3")}, activity={ActivityCode.SOFTWARE_CREATION: Decimal("1")})
    engineering_profile = profile(subject={DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("0.6"), DisciplineAreaCode.ENGINEERING_TECHNOLOGY: Decimal("0.4")}, activity={ActivityCode.PHYSICAL_ENGINEERING: Decimal("1")})
    economics_profile = profile(subject={DisciplineAreaCode.ECONOMICS_FINANCE: Decimal("0.7"), DisciplineAreaCode.BUSINESS_MANAGEMENT: Decimal("0.3")}, activity={ActivityCode.BUSINESS: Decimal("1")})
    data_profile = profile(subject={DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.6"), DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.4")}, activity={ActivityCode.DATA: Decimal("1")})

    assert _top_code(service, it_profile) == programs["it"].program_code
    assert _top_code(service, engineering_profile) == programs["engineering"].program_code
    assert _top_code(service, economics_profile) == programs["economics"].program_code
    assert _top_code(service, data_profile) == programs["data"].program_code


def test_strong_physics_anti_interest_penalizes_physics_heavy_program() -> None:
    service, programs = _service()
    liked_it = profile(subject={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")}, negative={})
    physics_anti = profile(subject={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")}, negative={DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("0.2")})
    strong_physics_anti = profile(subject={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")}, negative={DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("1")})

    without_penalty = service.recommend(RecommendationRequest(profile=liked_it, limit=4))
    with_penalty = service.recommend(RecommendationRequest(profile=physics_anti, limit=4))
    with_strong_penalty = service.recommend(RecommendationRequest(profile=strong_physics_anti, limit=4))
    eng_without = next(item for item in without_penalty.recommendations if item.program_code == programs["engineering"].program_code)
    eng_with = next(item for item in with_penalty.recommendations if item.program_code == programs["engineering"].program_code)
    eng_strong = next(item for item in with_strong_penalty.recommendations if item.program_code == programs["engineering"].program_code)
    assert eng_with.content_fit < eng_without.content_fit
    assert eng_strong.content_fit < eng_with.content_fit
