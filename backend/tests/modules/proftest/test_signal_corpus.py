from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import (
    ActivityCode,
    AdaptiveAnswer,
    Answer,
    AnswerSet,
    AnswerStatus,
    ProgramFingerprint,
)
from andromeda.modules.proftest.services.adaptive import AdaptiveCandidate, AdaptiveQuestionFactory, AdaptiveQuestionSelector
from andromeda.modules.proftest.services.profile_builder import UserProfileBuilder
from andromeda.modules.proftest.services.questionnaire import build_session_questionnaire
from andromeda.modules.recommendations.services.scoring import RecommendationScoringService


CORPUS_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "proftest" / "signal-corpus-v3.json"


def _corpus() -> list[dict[str, Any]]:
    data = cast(dict[str, Any], json.loads(CORPUS_PATH.read_text(encoding="utf-8")))
    assert data["corpus_version"] == "proftest-v3-signal-corpus.v1"
    assert data["question_set_version"] == build_session_questionnaire().question_set_version
    return cast(list[dict[str, Any]], data["personas"])


def _answer(item: dict[str, Any]) -> Answer:
    return Answer(
        question_id=cast(str, item["question_id"]),
        option_ids=tuple(cast(list[str], item["option_ids"])),
        intensity=Decimal(cast(str, item["intensity"])) if "intensity" in item else None,
        status=AnswerStatus(cast(str, item.get("status", "answered"))),
    )


@pytest.mark.parametrize("persona", _corpus(), ids=lambda persona: cast(str, persona["id"]))
def test_v3_persona_corpus_maps_answers_to_declared_signal_axes(persona: dict[str, Any]) -> None:
    questionnaire = build_session_questionnaire()
    answers = tuple(_answer(item) for item in cast(list[dict[str, Any]], persona["answers"]))
    profile = UserProfileBuilder().build(AnswerSet(answers=answers), questionnaire.questions)

    assert set(profile.preferred_subject_weights) >= {
        DisciplineAreaCode(value) for value in cast(list[str], persona["expected_subjects"])
    }
    assert set(profile.preferred_activity_weights) >= {
        ActivityCode(value) for value in cast(list[str], persona["expected_activities"])
    }
    assert set(profile.negative_weights) >= {
        DisciplineAreaCode(value) for value in cast(list[str], persona["expected_negative"])
    }
    assert profile.confidence.answered_base == persona["expected_answered_base"]
    if not persona["expected_subjects"] and not persona["expected_activities"] and not persona["expected_negative"]:
        assert profile.preferred_subject_weights == {}
        assert profile.preferred_activity_weights == {}
        assert profile.negative_weights == {}


def test_every_v3_question_declares_its_signal_effect_without_hidden_weights() -> None:
    questionnaire = build_session_questionnaire()

    for question in questionnaire.questions:
        assert question.declared_dimensions
        for option in question.options:
            has_content_signal = bool(option.subject_weights or option.activity_weights)
            has_anti_signal = bool(option.anti_interest_weights)
            if option.id in {"dont_know", "learning_dont_know", "no_exclusions"}:
                assert not has_content_signal and not has_anti_signal
            elif question.id == "core_anti":
                assert has_anti_signal
                assert not has_content_signal
            else:
                assert has_content_signal
                assert not has_anti_signal


def _candidate(code: str, computer: str, mathematics: str) -> ProgramFingerprint:
    return ProgramFingerprint(
        program_id=f"program:{code}",
        program_code=code,
        program_name=code,
        basis="hours",
        total_hours=100,
        total_credits=Decimal("10"),
        total_workload=Decimal("100"),
        area_hours={
            DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal(computer) * 100,
            DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal(mathematics) * 100,
        },
        area_share={
            DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal(computer),
            DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal(mathematics),
        },
        semester_distribution={"1": Decimal("1")},
        activity_signals={
            ActivityCode.SOFTWARE_CREATION: Decimal("0.5"),
            ActivityCode.DATA: Decimal("0.5"),
        },
    )


def test_adaptive_question_is_deterministic_and_changes_a_known_signal_axis() -> None:
    persona = next(item for item in _corpus() if item["id"] == "software-builder")
    questionnaire = build_session_questionnaire()
    answers = tuple(_answer(item) for item in cast(list[dict[str, Any]], persona["answers"]))
    base_profile = UserProfileBuilder().build(AnswerSet(answers=answers), questionnaire.questions)
    candidates = (
        AdaptiveCandidate(_candidate("09.03.01-01", "0.8", "0.2"), Decimal("80")),
        AdaptiveCandidate(_candidate("09.03.01-02", "0.2", "0.8"), Decimal("79")),
    )
    selector = AdaptiveQuestionSelector()
    first = selector.select(candidates, base_profile)
    second = selector.select(candidates, base_profile)
    question = AdaptiveQuestionFactory().create(first)
    assert first == second
    assert question is not None

    adaptive_profile = UserProfileBuilder().build(
        AnswerSet(
            answers=answers,
            adaptive_answers=(
                AdaptiveAnswer(
                    question_id=question.id,
                    option_id=question.options[1].id,
                    dimension=question.declared_dimensions[1],
                ),
            ),
        ),
        questionnaire.questions,
        (question,),
    )
    scorer = RecommendationScoringService()
    before = tuple(scorer.score(base_profile, item.fingerprint).content_fit for item in candidates)
    after = tuple(scorer.score(adaptive_profile, item.fingerprint).content_fit for item in candidates)

    assert before != after
    assert adaptive_profile.confidence_by_dimension[question.declared_dimensions[1]] == Decimal("1.0000")
