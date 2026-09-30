from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.composition import container as container_module
from andromeda.modules.presentation.contracts.verbalization import (
    ResponseNaturalizationResult,
    ResponseNaturalizedSection,
    section_reference_id,
)

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from run_andromeda_bmstu import run_ingest  # noqa: I001


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def _client(
    tmp_path: Path,
    *,
    policy_enabled: bool = False,
    presentation_enabled: bool = False,
) -> TestClient:
    database_url = f"sqlite:///{(tmp_path / 'assistant-api.db').as_posix()}"
    run_ingest(
        mode="fixture",
        fixture_dir=FIXTURE_DIR,
        database_url=database_url,
        program_codes=(),
    )
    with patch.dict(
        os.environ,
        {
            "ANDROMEDA_KNOWLEDGE_POLICY_ASSISTANT_ENABLED": str(policy_enabled).lower(),
            "PRESENTATION_LLM_ENABLED": str(presentation_enabled).lower(),
            "POLZA_AI_API_KEY": "test-key" if presentation_enabled else "",
        },
    ):
        app = create_app(database_url)
    return TestClient(app)


def test_assistant_admission_flow_keeps_typed_session_state(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.post("/assistant/query", json={"text": "Куда я прохожу с 270?"})
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["state"] == "needs_clarification"
        assert first_payload["missing_slots"] == ["exams"]

        second = client.post(
            "/assistant/query",
            json={
                "text": "русский 90, математика 90, информатика 90",
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )
        assert second.status_code == 200, second.text
        second_payload = second.json()
        assert second_payload["state"] == "needs_clarification"
        assert second_payload["missing_slots"] == ["funding"]

        third = client.post(
            "/assistant/query",
            json={
                "text": "university:bmstu",
                "sessionId": second_payload["session_id"],
                "expectedRevision": second_payload["revision"],
            },
        )
        assert third.status_code == 200, third.text
        third_payload = third.json()
        assert third_payload["state"] == "needs_clarification"
        assert third_payload["missing_slots"] == ["funding"]
        assert "бюджет или платное" in third_payload["question"].casefold()
        assert third_payload["options"] == ["Бюджет", "Платное"]

        fourth = client.post(
            "/assistant/query",
            json={
                "text": "бюджет",
                "sessionId": third_payload["session_id"],
                "expectedRevision": third_payload["revision"],
            },
        )
        assert fourth.status_code == 200, fourth.text
        fourth_payload = fourth.json()
        assert fourth_payload["state"] == "complete"
        assert fourth_payload["admission_request"]["program_ids"]
        assert fourth_payload["admission_result"]["by_program_id"]
        assert fourth_payload["admission_request"]["admission_year"] == 2026
        assert fourth_payload["admission_request"]["study_form"] == "full_time"
        assert fourth_payload["admission_request"]["funding_type"] == "budget"
        assert fourth_payload["response"]["template"] == "admission-fit-summary"
        assert "2026" in fourth_payload["response"]["text"]
        assert "очная" in fourth_payload["response"]["text"]
        assert "последний опубликованный год" in fourth_payload["response"]["text"]
        assert fourth_payload["response"]["metadata"]["assumptions"] == [
            "Год приёма: 2026 (последний опубликованный год)",
            "Форма обучения: очная (по умолчанию)",
        ]

        fifth = client.post(
            "/assistant/query",
            json={
                "text": "То есть с этими баллами я точно поступлю?",
                "sessionId": fourth_payload["session_id"],
                "expectedRevision": fourth_payload["revision"],
            },
        )
        assert fifth.status_code == 200, fifth.text
        fifth_payload = fifth.json()
        assert fifth_payload["state"] == "complete"
        assert fifth_payload["revision"] == fourth_payload["revision"] + 1
        assert "гарантировать поступление нельзя" in fifth_payload["response"]["text"]
        assert fifth_payload["admission_result"] == fourth_payload["admission_result"]


def test_pending_admission_can_switch_to_source_backed_program_card(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        pending = client.post(
            "/assistant/query", json={"text": "Оценить поступление"}
        ).json()
        card_response = client.post(
            "/assistant/query",
            json={
                "text": "Расскажи о программе 09.03.01-02",
                "sessionId": pending["session_id"],
                "expectedRevision": pending["revision"],
            },
        )
        assert card_response.status_code == 200, card_response.text
        card = card_response.json()
        assert card["state"] == "complete"
        assert card["revision"] == pending["revision"] + 1
        assert card["response"]["template"] == "program-details"
        assert card["response"]["data"]["program_id"] == "program:bmstu:09.03.01-02"
        assert "Источник программы:" in card["response"]["text"]
        assert "баллы ЕГЭ" not in card["response"]["text"]

        curriculum_response = client.post(
            "/assistant/query",
            json={
                "text": "А какие дисциплины на первом курсе?",
                "sessionId": card["session_id"],
                "expectedRevision": card["revision"],
            },
        )
        assert curriculum_response.status_code == 200, curriculum_response.text
        curriculum = curriculum_response.json()
        assert curriculum["state"] == "complete"
        assert curriculum["response"]["template"] == "program-details"
        assert curriculum["response"]["data"]["curriculum"]["course_year"] == 1
        assert "Источник учебного плана:" in curriculum["response"]["text"]

        revision = curriculum["revision"]
        for question in (
            "Сколько там программирования?",
            "А математики?",
            "Какие конкретно дисциплины ты отнёс к программированию?",
            "Сколько часов и ЗЕТ?",
        ):
            follow_up = client.post(
                "/assistant/query",
                json={
                    "text": question,
                    "sessionId": card["session_id"],
                    "expectedRevision": revision,
                },
            )
            assert follow_up.status_code == 200, follow_up.text
            result = follow_up.json()
            assert result["state"] == "complete", result
            assert result["response"] is not None
            revision = result["revision"]


def test_olympiad_inquiry_asks_for_olympiad_then_year_without_program(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        previous = client.post(
            "/assistant/query", json={"text": "Оценить поступление в 2027 году"}
        ).json()
        first_response = client.post(
            "/assistant/query",
            json={
                "text": "У меня диплом олимпиады, что он даёт?",
                "sessionId": previous["session_id"],
                "expectedRevision": previous["revision"],
            },
        )
        assert first_response.status_code == 200, first_response.text
        first = first_response.json()
        assert first["state"] == "needs_clarification"
        assert first["missing_slots"] == ["olympiad"]
        assert "название олимпиады" in first["question"]
        assert "программу" not in first["question"]

        second_response = client.post(
            "/assistant/query",
            json={
                "text": "Высшая проба",
                "sessionId": first["session_id"],
                "expectedRevision": first["revision"],
            },
        )
        assert second_response.status_code == 200, second_response.text
        second = second_response.json()
        assert second["state"] == "needs_clarification"
        assert second["missing_slots"] == ["admission_year"]

        third_response = client.post(
            "/assistant/query",
            json={
                "text": "2026",
                "sessionId": second["session_id"],
                "expectedRevision": second["revision"],
            },
        )
        assert third_response.status_code == 200, third_response.text
        third = third_response.json()
        assert third["state"] == "complete"
        assert third["response"]["template"] == "olympiad-benefits"
        assert third["response"]["data"]["admission_year"] == 2026
        assert "пробел покрытия" in third["response"]["text"] or "опубликованные условия" in third["response"]["text"]


def test_incomplete_exam_reply_repeats_guidance_without_revision_conflict(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = client.post("/assistant/query", json={"text": "Оценить поступление"})
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["state"] == "needs_clarification"
        assert first_payload["options"] == []
        assert "баллы ЕГЭ" in first_payload["question"]
        assert not any(character.isdigit() for character in first_payload["question"])

        second = client.post(
            "/assistant/query",
            json={
                "text": "Русский язык",
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )
        assert second.status_code == 200, second.text
        second_payload = second.json()
        assert second_payload["session_id"] == first_payload["session_id"]
        assert second_payload["revision"] == first_payload["revision"]
        assert second_payload["question"] == first_payload["question"]


def test_enabled_conversation_ai_keeps_slot_clarification_typed_and_grounded(
    tmp_path: Path,
) -> None:
    from andromeda.modules.conversation.contracts.language import (
        AssistantQueryInterpretation,
    )
    from andromeda.modules.conversation.contracts.public import ConversationIntent

    class StubConversationAI:
        def __init__(self, _settings: object) -> None:
            pass

        def interpret(self, _text: str, **_kwargs: object) -> AssistantQueryInterpretation:
            return AssistantQueryInterpretation(intent=ConversationIntent.ADMISSION_SEARCH)

        def select_catalog_candidate(self, *_args: object, **_kwargs: object) -> str | None:
            return None

    provider = StubConversationAI
    with (
        patch.object(container_module, "PolzaConversationAI", provider),
        _client(tmp_path, presentation_enabled=True) as client,
    ):
        result = client.post("/assistant/query", json={"text": "Оцени мои шансы на поступление"})

    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["state"] == "needs_clarification"
    assert "год" in payload["question"].casefold()
    assert "поступ" in payload["question"].casefold()
    assert payload["missing_slots"] == ["admission_year"]
    assert not any(character.isdigit() for character in payload["question"])


def test_conversation_provider_timeout_uses_program_catalog_during_task_switch(
    tmp_path: Path,
) -> None:
    class TimedOutConversationAI:
        def __init__(self, _settings: object) -> None:
            pass

        def interpret(self, _text: str, **_kwargs: object) -> None:
            raise TimeoutError("provider unavailable")

    with (
        patch.object(container_module, "PolzaConversationAI", TimedOutConversationAI),
        _client(tmp_path, presentation_enabled=True) as client,
    ):
        pending_response = client.post(
            "/assistant/query", json={"text": "Оценить поступление"}
        )
        assert pending_response.status_code == 200, pending_response.text
        pending = pending_response.json()
        assert pending["state"] == "needs_clarification"

        card_response = client.post(
            "/assistant/query",
            json={
                "text": "Расскажи о программе 09.03.01-02",
                "sessionId": pending["session_id"],
                "expectedRevision": pending["revision"],
            },
        )
        assert card_response.status_code == 200, card_response.text
        card = card_response.json()
        assert card["state"] == "complete"
        assert card["response"]["template"] == "program-details"
        assert "Источник программы:" in card["response"]["text"]


def test_comparison_starts_by_asking_which_programs_then_returns_summary_first(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = client.post("/assistant/query", json={"text": "Сравнить программы"})
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["state"] == "needs_clarification"
        assert first_payload["missing_slots"] == ["entity"]
        assert "программы" in first_payload["question"].casefold()
        assert "своими словами" in first_payload["question"].casefold()

        second = client.post(
            "/assistant/query",
            json={
                "text": "program:bmstu:09.03.01-02 и program:bmstu:09.03.01-12",
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )
        assert second.status_code == 200, second.text
        second_payload = second.json()
        assert second_payload["state"] == "complete"
        assert second_payload["missing_slots"] == []
        assert second_payload["session_id"] == first_payload["session_id"]
        response = second_payload["response"]
        assert response["template"] == "metric-comparison"
        assert len(response["data"]["rows"]) == 2
        assert response["data"]["rows"][0]["metrics"]


def test_comparison_resolves_free_text_program_names_before_asking_for_metric(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = client.post("/assistant/query", json={"text": "Сравнить программы"})
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["missing_slots"] == ["entity"]

        second = client.post(
            "/assistant/query",
            json={
                "text": (
                    "Интеллектуальные системы обработки информации и управления и "
                    "Искусственный интеллект в системах обработки информации и управления"
                ),
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )
        assert second.status_code == 200, second.text
        second_payload = second.json()
        assert second_payload["state"] == "complete"
        assert second_payload["missing_slots"] == []
        assert second_payload["response"]["template"] == "metric-comparison"
        assert len(second_payload["response"]["data"]["rows"]) == 2


def test_initial_comparison_resolves_two_catalog_names_without_provider(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/assistant/query",
            json={
                "text": (
                    "Сравни Интеллектуальные системы обработки информации и управления "
                    "и Искусственный интеллект в системах обработки информации и управления"
                )
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["state"] == "complete"
        assert payload["response"]["template"] == "metric-comparison"
        assert len(payload["response"]["data"]["rows"]) == 2


def test_completed_comparison_keeps_context_for_metric_only_follow_up(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = client.post("/assistant/query", json={"text": "Сравнить программы"})
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["state"] == "needs_clarification"

        second = client.post(
            "/assistant/query",
            json={
                "text": (
                    "Интеллектуальные системы обработки информации и управления и "
                    "Искусственный интеллект в системах обработки информации и управления"
                ),
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )
        assert second.status_code == 200, second.text
        second_payload = second.json()
        assert second_payload["state"] == "complete"
        assert len(second_payload["response"]["data"]["rows"]) == 2

        follow_up = client.post(
            "/assistant/query",
            json={
                "text": "А теперь только по программированию и математике.",
                "sessionId": second_payload["session_id"],
                "expectedRevision": second_payload["revision"],
            },
        )

    assert follow_up.status_code == 200, follow_up.text
    follow_up_payload = follow_up.json()
    assert follow_up_payload["state"] == "complete"
    assert follow_up_payload["session_id"] == second_payload["session_id"]
    assert follow_up_payload["revision"] > second_payload["revision"]
    assert set(follow_up_payload["query"]["metrics"]) == {
        "programming_share",
        "math_share",
    }
    assert len(follow_up_payload["response"]["data"]["rows"]) == 2


def test_unmatched_free_text_keeps_comparison_context_and_explains_catalog_gap(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = client.post("/assistant/query", json={"text": "Сравнить программы"})
        assert first.status_code == 200, first.text
        first_payload = first.json()

        second = client.post(
            "/assistant/query",
            json={
                "text": "бизнес информатика",
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )
        assert second.status_code == 200, second.text
        second_payload = second.json()
        assert second_payload["state"] == "needs_clarification"
        assert second_payload["missing_slots"] == ["entity"]
        assert "не нашла" in second_payload["question"].casefold()

        third = client.post(
            "/assistant/query",
            json={
                "text": "бизнес информатика и программная инженерия",
                "sessionId": second_payload["session_id"],
                "expectedRevision": second_payload["revision"],
            },
        )
        assert third.status_code == 200, third.text
        third_payload = third.json()
        assert third_payload["state"] == "needs_clarification"
        assert third_payload["missing_slots"] == ["entity"]
        assert "не нашла" in third_payload["question"].casefold()
        assert "Какую программу" not in third_payload["question"]


def test_unrecognized_message_after_completed_admission_does_not_repeat_old_result(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = client.post(
            "/assistant/query",
            json={
                "text": (
                    "Куда поступить в 2026 году очно на бюджет: русский 90, "
                    "математика 90, физика 90, university:bmstu"
                )
            },
        )
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["state"] == "complete"

        follow_up = client.post(
            "/assistant/query",
            json={
                "text": "и че",
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )

        assert follow_up.status_code == 200, follow_up.text
        payload = follow_up.json()
        assert payload["state"] == "needs_clarification"
        assert payload["session_id"] == first_payload["session_id"]
        assert payload["revision"] > first_payload["revision"]
        assert payload["options"] == []
        assert "своими словами" in payload["question"].casefold()


def test_assistant_uses_explicit_admission_filters_without_reasking(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        result = client.post(
            "/assistant/query",
            json={
                "text": (
                    "Куда поступить в 2026 году очно на бюджет: русский 90, "
                    "математика 90, физика 90, university:bmstu"
                )
            },
        )

        assert result.status_code == 200, result.text
        payload = result.json()
        assert payload["state"] == "complete"
        request = payload["admission_request"]
        assert request["admission_year"] == 2026
        assert request["study_form"] == "full_time"
        assert request["funding_type"] == "budget"
        assert "последний опубликованный год" not in payload["response"]["text"]
        assert payload["response"]["metadata"]["assumptions"] == []
        report_outcomes = payload["response"]["data"]["outcomes"]["by_program_id"]
        assert {
            outcome["result"]["program_name"]
            for outcome in report_outcomes.values()
        } == {
            "Интеллектуальные системы обработки информации и управления",
            "Искусственный интеллект в системах обработки информации и управления",
        }


def test_assistant_multiple_university_choice_asks_for_names_instead_of_repeating_scope(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = client.post(
            "/assistant/query",
            json={
                "text": "Куда я прохожу: русский 80, математика 85, информатика 88"
            },
        )
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["state"] == "needs_clarification"
        assert first_payload["missing_slots"] == ["funding"]

        result = client.post(
            "/assistant/query",
            json={
                "text": "Несколько вузов",
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )

        assert result.status_code == 200, result.text
        payload = result.json()
        assert payload["state"] == "needs_clarification"
        assert payload["session_id"] == first_payload["session_id"]
        assert payload["revision"] == first_payload["revision"] + 1
        assert payload["question"] == (
            "Напишите название одного или нескольких вузов через запятую."
        )
        assert payload["options"] == []


def test_assistant_accepts_any_university_scope_and_checks_full_fixture_catalog(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = client.post(
            "/assistant/query",
            json={
                "text": "Куда я прохожу с 270: русский 90, математика 90, информатика 90"
            },
        )
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["state"] == "needs_clarification"
        assert first_payload["missing_slots"] == ["funding"]

        result = client.post(
            "/assistant/query",
            json={
                "text": "Любые вузы",
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )

        assert result.status_code == 200, result.text
        clarification = result.json()
        assert clarification["state"] == "needs_clarification"
        assert clarification["missing_slots"] == ["funding"]

        result = client.post(
            "/assistant/query",
            json={
                "text": "платное",
                "sessionId": clarification["session_id"],
                "expectedRevision": clarification["revision"],
            },
        )
        assert result.status_code == 200, result.text
        payload = result.json()
        assert payload["state"] == "complete"
        assert payload["admission_request"]["funding_type"] == "paid"
        assert payload["admission_request"]["admission_year"] == 2026
        assert payload["admission_request"]["study_form"] == "full_time"
        assert payload["admission_result"]["by_program_id"]
        submitted_ids = tuple(
            program_id
            for batch in payload["admission_requests"]
            for program_id in batch["program_ids"]
        )
        assert set(payload["admission_result"]["by_program_id"]) == set(submitted_ids)


def test_assistant_analytics_flow_returns_channel_neutral_envelope(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/assistant/query",
            json={
                "text": "Где больше математики между program:bmstu:09.03.01-02 и program:bmstu:09.03.01-12?",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["state"] == "complete"
        assert payload["query"]["scope"] == "program"
        assert payload["response"]["response_type"] == "image"
        assert payload["response"]["template"] == "metric-comparison"


def test_ordinary_assistant_envelope_uses_the_existing_naturalizer_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []

    class EchoNaturalizer:
        def __init__(self, _settings: object) -> None:
            pass

        def naturalize(self, request, *, rate_limit_key: str):  # type: ignore[no-untyped-def]
            assert rate_limit_key
            requests.append(request)
            return ResponseNaturalizationResult(
                sections=tuple(
                    ResponseNaturalizedSection(
                        section_id=section.section.section_id,
                        text=section.text,
                        reference_ids=(
                            section_reference_id(section.section.section_id),
                        ),
                    )
                    for section in request.sections
                )
            )

    class StubConversationAI:
        def __init__(self, _settings: object) -> None:
            pass

        def interpret(self, _text: str, **_kwargs: object):  # type: ignore[no-untyped-def]
            from andromeda.modules.conversation.contracts.language import (
                AssistantEntityMention,
                AssistantQueryInterpretation,
            )
            from andromeda.modules.conversation.contracts.public import (
                ConversationIntent,
            )
            from andromeda.modules.entity_resolution.contracts.public import (
                ResolutionEntityType,
            )

            program_queries = (
                "program:bmstu:09.03.01-02",
                "program:bmstu:09.03.01-12",
            )
            return AssistantQueryInterpretation(
                intent=ConversationIntent.COMPARE_PROGRAMS,
                entities=tuple(
                    AssistantEntityMention(
                        entity_type=ResolutionEntityType.PROGRAM,
                        query=query,
                    )
                    for query in program_queries
                ),
                metric_codes=("math_share",),
            )

        def clarify(self, *_args: object, **_kwargs: object) -> str:
            raise AssertionError("complete query must not request clarification")

        def select_catalog_candidate(self, *_args: object, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(container_module, "PolzaNaturalizer", EchoNaturalizer)
    monkeypatch.setattr(container_module, "PolzaConversationAI", StubConversationAI)

    with _client(tmp_path, presentation_enabled=True) as client:
        response = client.post(
            "/assistant/query",
            json={
                "text": "Где больше математики между program:bmstu:09.03.01-02 и program:bmstu:09.03.01-12?"
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["state"] == "complete"
    assert payload["response"]["response_mode"] == "source_backed_verbalization"
    assert len(requests) == 1
    assert len(requests[0].sections) == 1
    assert requests[0].sections[0].text == payload["response"]["text"]
    assert requests[0].allowed_references == ()


def test_assistant_policy_rumor_without_a_source_claim_stays_unknown(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, policy_enabled=True) as client:
        response = client.post(
            "/assistant/query",
            json={"text": "Правда ли, что с 2028 года введут четвертый ЕГЭ?"},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["state"] == "complete"
        assert "policy_answer" not in payload
        assert payload["response"]["response_mode"] == "deterministic"
        assert payload["response"]["knowledge"]["status"] == "no_evidence"
        assert payload["response"]["knowledge"]["source_assertions"] == []
        assert "не доказывает" in payload["response"]["text"].casefold()


def test_outside_coverage_uses_unverified_mode_without_persisting_answer(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, policy_enabled=True) as client:
        outside = client.post(
            "/assistant/query",
            json={"text": "Что сейчас обсуждают по новому закону о поступлении?"},
        )
        assert outside.status_code == 200, outside.text
        outside_payload = outside.json()
        outside_response = outside_payload["response"]
        assert outside_response["response_mode"] == "unverified_fallback"
        assert outside_response["knowledge"]["status"] == "outside_coverage"
        assert outside_response["knowledge"]["source_assertions"] == []
        assert outside_response["knowledge"]["evidence"] == []
        assert "общий ответ не предоставлен" in outside_response["text"].casefold()

        verified_path = client.post(
            "/assistant/query",
            json={
                "text": "Правда ли, что с 2028 года введут четвертый ЕГЭ?",
                "sessionId": outside_payload["session_id"],
                "expectedRevision": outside_payload["revision"],
            },
        )
        assert verified_path.status_code == 200, verified_path.text
        verified_response = verified_path.json()["response"]
        assert verified_response["response_mode"] == "deterministic"
        assert verified_response["knowledge"]["status"] == "no_evidence"


def test_assistant_policy_applicability_clarifies_then_returns_resolver_trace(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, policy_enabled=True) as client:
        first = client.post(
            "/assistant/query",
            json={"text": "Четвертый ЕГЭ меня касается для university:bmstu?"},
        )
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["state"] == "needs_clarification"
        assert first_payload["missing_slots"] == ["admission_year"]

        second = client.post(
            "/assistant/query",
            json={
                "text": "Поступаю в 2027 году",
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )
        assert second.status_code == 200, second.text
        payload = second.json()
        assert payload["state"] == "complete"
        assert "policy_answer" not in payload
        assert payload["response"]["knowledge"]["status"] == "no_evidence"
        assert "не доказывает" in payload["response"]["text"].casefold()


def test_policy_follow_ups_keep_topic_after_year_and_date_questions(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, policy_enabled=True) as client:
        revision: int | None = None
        session_id: str | None = None
        turns = (
            ("Говорят, со следующего года введут четвёртый ЕГЭ. Это правда?", "complete"),
            ("А меня это касается?", "needs_clarification"),
            ("Поступаю в 2028", "complete"),
            ("А с какого числа оно действует?", "complete"),
            ("А как это правило работало в 2026 году?", "complete"),
        )
        for question, expected_state in turns:
            request: dict[str, object] = {"text": question}
            if session_id is not None:
                request.update({"sessionId": session_id, "expectedRevision": revision})
            response = client.post("/assistant/query", json=request)
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["state"] == expected_state, result
            if expected_state == "complete":
                assert result["response"]["template"] == "policy-resolution"
            session_id = result["session_id"]
            revision = result["revision"]


def test_shadow_provider_timeout_does_not_turn_assistant_request_into_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from andromeda.infrastructure.config.settings import Settings
    from andromeda.infrastructure.jev import runtime as jev_runtime

    database_url = f"sqlite:///{(tmp_path / 'assistant-shadow-fallback.db').as_posix()}"
    run_ingest(
        mode="fixture",
        fixture_dir=FIXTURE_DIR,
        database_url=database_url,
        program_codes=(),
    )
    shadow_settings = Settings(
        database_url=database_url,
        environment="development",
        jev_shadow_enabled=True,
        jev_runtime_provider="typesafe",
        jev_endpoint="https://polza.ai/api",
        jev_model="typesafe/jev",
        jev_api_key="test-placeholder-not-a-credential",
    )
    monkeypatch.setattr(
        Settings,
        "from_environment",
        classmethod(
            lambda cls, selected_database_url=None: replace(
                shadow_settings,
                database_url=selected_database_url or shadow_settings.database_url,
            )
        ),
    )

    transport_instances = []

    class _FailingTransport:
        def __init__(self, **kwargs) -> None:
            del kwargs
            self.request_count = 0
            transport_instances.append(self)

        @staticmethod
        def health_check() -> bool:
            return True

        def request_envelope(self, request):  # type: ignore[no-untyped-def]
            del request
            self.request_count += 1
            raise TimeoutError("synthetic provider timeout")

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(jev_runtime, "TypeSafeJevTransport", _FailingTransport)

    with TestClient(create_app(database_url)) as client:
        response = client.post(
            "/assistant/query",
            json={"text": "Куда я прохожу с 270 баллами?"},
        )

    assert transport_instances
    assert transport_instances[0].request_count > 0
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["state"] == "needs_clarification"
    assert payload["missing_slots"] == ["exams"]
    assert payload["question"].startswith("Какие баллы ЕГЭ у вас есть?")
    assert not any(character.isdigit() for character in payload["question"])


def test_assistant_keeps_a_live_multi_turn_discovery_and_score_update_context(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = client.post(
            "/assistant/query",
            json={"text": "Хочу поступать куда-нибудь в IT, не понимаю куда"},
        )
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["state"] == "complete"
        assert first_payload["response"]["template"] == "program-recommendations"
        recommendations = first_payload["response"]["data"]["recommendations"]
        assert recommendations
        assert all(item["program_id"].startswith("program:") for item in recommendations)
        assert all(item["provenance"] for item in recommendations)
        assert "не прогноз поступления" in first_payload["response"]["text"]

        second = client.post(
            "/assistant/query",
            json={
                "text": "нравится ИИ, но не хочу много математики",
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )
        assert second.status_code == 200, second.text
        second_payload = second.json()
        assert second_payload["state"] == "complete"
        assert second_payload["session_id"] == first_payload["session_id"]
        assert set(second_payload["response"]["data"]["preferred_areas"]) == {
            "computer_science_data"
        }
        assert set(second_payload["response"]["data"]["avoided_areas"]) == {
            "mathematics_statistics"
        }

        third = client.post(
            "/assistant/query",
            json={
                "text": "а что из этого есть в Бауманке?",
                "sessionId": second_payload["session_id"],
                "expectedRevision": second_payload["revision"],
            },
        )
        assert third.status_code == 200, third.text
        third_payload = third.json()
        assert third_payload["state"] == "complete"
        assert third_payload["session_id"] == first_payload["session_id"]
        assert third_payload["response"]["metadata"]["restricted_to_previous_candidates"] is True
        bmstu_rows = third_payload["response"]["data"]["recommendations"]
        assert bmstu_rows
        assert all(item["program_id"].startswith("program:bmstu:") for item in bmstu_rows)
        assert all(item["university_id"] == "university:bmstu" for item in bmstu_rows)

        admission = client.post(
            "/assistant/query",
            json={
                "text": (
                    "Куда я прохожу с 270: русский 90, математика 90, информатика 90, "
                    "university:bmstu, бюджет"
                ),
                "sessionId": third_payload["session_id"],
                "expectedRevision": third_payload["revision"],
            },
        )
        assert admission.status_code == 200, admission.text
        admission_payload = admission.json()
        assert admission_payload["state"] == "complete"

        changed_total = client.post(
            "/assistant/query",
            json={
                "text": "А если 285?",
                "sessionId": admission_payload["session_id"],
                "expectedRevision": admission_payload["revision"],
            },
        )
        assert changed_total.status_code == 200, changed_total.text
        changed_payload = changed_total.json()
        assert changed_payload["state"] == "needs_clarification"
        assert changed_payload["missing_slots"] == ["exams"]
        assert "не буду сама распределять" in changed_payload["question"].casefold()

        updated_scores = client.post(
            "/assistant/query",
            json={
                "text": "информатика 95",
                "sessionId": changed_payload["session_id"],
                "expectedRevision": changed_payload["revision"],
            },
        )
        assert updated_scores.status_code == 200, updated_scores.text
        updated_payload = updated_scores.json()
        assert updated_payload["state"] == "complete"
        scores = updated_payload["admission_request"]["applicant"]["scores"]
        assert {item["subject"]: item["score"] for item in scores} == {
            "русский язык": "90",
            "математика": "90",
            "информатика": "95",
        }
