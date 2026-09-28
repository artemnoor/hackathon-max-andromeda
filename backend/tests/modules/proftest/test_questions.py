from __future__ import annotations

from andromeda.modules.proftest.domain.entities import QuestionBlock
from andromeda.modules.proftest.contracts.public import QuestionComponentType
from andromeda.modules.proftest.services.questionnaire import (
    build_questionnaire,
    build_session_questionnaire,
    build_session_questionnaire_v2,
    session_questionnaire,
)


def test_questionnaire_contains_separate_interest_activity_and_anti_interest_blocks() -> None:
    questionnaire = build_questionnaire()
    blocks = {question.block for question in questionnaire.questions}
    assert {QuestionBlock.INTERESTS, QuestionBlock.ACTIVITIES, QuestionBlock.ANTI_INTERESTS} <= blocks
    assert all("program:" not in option.id for question in questionnaire.questions for option in question.options)
    anti = next(question for question in questionnaire.questions if question.id == "anti_subjects")
    assert anti.multi_select is True
    assert anti.max_selected == 3


def test_session_questionnaire_is_versioned_deterministic_and_has_mechanics_budget() -> None:
    first = build_session_questionnaire()
    second = build_session_questionnaire()

    assert first == second
    assert first.question_set_version == "proftest-v3"
    assert len(first.questions) == 5
    assert {question.component_type for question in first.questions} >= {
        QuestionComponentType.PAIR_CHOICE,
        QuestionComponentType.SCENARIO_CHOICE,
        QuestionComponentType.MULTI_CHOICE,
    }
    assert tuple(question.id for question in first.questions) == (
        "core_doing",
        "core_learning",
        "core_result",
        "core_task_mode",
        "core_anti",
    )
    assert first.questions[0].max_selected == 3
    assert first.questions[1].max_selected == 3
    assert first.questions[4].max_selected == 3
    assert all(question.order == index for index, question in enumerate(first.questions, start=1))
    assert all(question.declared_dimensions for question in first.questions)
    assert all("program:" not in option.id for question in first.questions for option in question.options)


def test_published_v2_questionnaire_and_registry_are_preserved() -> None:
    v2 = build_session_questionnaire_v2()

    assert v2.question_set_version == "proftest-v2"
    assert len(v2.questions) == 24
    assert session_questionnaire("proftest-v2") == v2
    assert session_questionnaire("proftest-v3") == build_session_questionnaire()
