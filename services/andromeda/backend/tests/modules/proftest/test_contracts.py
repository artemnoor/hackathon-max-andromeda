from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode, DisciplineAreaWeight
from andromeda.modules.proftest.contracts.public import (
    ActivityCode,
    Answer,
    AnswerSet,
    AntiInterest,
    Confidence,
    CurriculumEvidence,
    ProfileScope,
    PreliminaryProfile,
    PreliminaryTopic,
    ProgramFingerprint,
    UserProfile,
    UserProfileSnapshot,
)


def test_public_contracts_are_strict() -> None:
    contracts = (Answer, AnswerSet, AntiInterest, Confidence, CurriculumEvidence, ProfileScope, ProgramFingerprint, UserProfile, UserProfileSnapshot)
    assert all(contract.model_config["extra"] == "forbid" for contract in contracts)


def test_user_profile_keeps_subject_and_activity_axes_separate() -> None:
    profile = UserProfile(
        interests=(DisciplineAreaCode.COMPUTER_SCIENCE_DATA,),
        activity_preferences=(ActivityCode.SYSTEM_DESIGN,),
        preferred_subject_weights={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")},
        preferred_activity_weights={ActivityCode.SYSTEM_DESIGN: Decimal("1")},
        anti_interests=(AntiInterest(area=DisciplineAreaCode.PHYSICS_ASTRONOMY, intensity=Decimal("0.9")),),
        negative_weights={DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("0.9")},
        confidence=Confidence(value=Decimal("0.8"), answered_base=8, answered_adaptive=1),
    )
    assert profile.interests == (DisciplineAreaCode.COMPUTER_SCIENCE_DATA,)
    assert profile.activity_preferences == (ActivityCode.SYSTEM_DESIGN,)
    assert profile.negative_weights[DisciplineAreaCode.PHYSICS_ASTRONOMY] == Decimal("0.9")


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Answer(question_id="q1", option_ids=("o1",), unexpected="value")


def test_profile_rejects_non_normalized_positive_distribution() -> None:
    with pytest.raises(ValidationError):
        UserProfile(preferred_subject_weights={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.4")})


def test_evidence_requires_area_weights_to_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        CurriculumEvidence(
            source_name="Математика",
            normalized_name="математика",
            hours=100,
            workload=Decimal("100"),
            area_weights=(DisciplineAreaWeight(area=DisciplineAreaCode.MATHEMATICS_STATISTICS, weight=Decimal("0.4")),),
        )


def test_preliminary_contract_exposes_only_bounded_topics() -> None:
    preliminary = PreliminaryProfile(
        topics=(
            PreliminaryTopic(code="area:computer_science_data", label="Информатика и данные"),
            PreliminaryTopic(code="area:mathematics_statistics", label="Математика и статистика"),
        )
    )

    assert len(preliminary.topics) == 2
    assert set(preliminary.topics[0].model_dump()) == {"code", "label"}
    assert PreliminaryProfile.model_config["extra"] == "forbid"
