from __future__ import annotations

import json

import httpx

from andromeda.infrastructure.adapters.polza_conversation_ai import PolzaConversationAI
from andromeda.infrastructure.config.settings import Settings
from andromeda.modules.admissions.contracts.public import FundingType
from andromeda.modules.conversation.contracts.language import (
    AssistantClarificationRequest,
    AssistantEntityCandidate,
)
from andromeda.modules.conversation.contracts.public import (
    AdmissionUniversityScope,
    ConversationIntent,
    ConversationSlot,
)
from andromeda.modules.entity_resolution.contracts.public import ResolutionEntityType


def test_polza_conversation_operations_use_bounded_typed_provider_contracts() -> None:
    observed: list[httpx.Request] = []
    candidate = AssistantEntityCandidate(
        entity_type=ResolutionEntityType.PROGRAM,
        canonical_id="program:bmstu:09.03.01-02",
        label="09.03.01 — Информатика и вычислительная техника",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        payload = json.loads(request.content)
        system_prompt = payload["messages"][0]["content"]
        if "Extract one user turn" in system_prompt:
            result = {
                "intent": "compare_programs",
                "entities": [{"entity_type": "program", "query": "бизнес-информатика"}],
                "metric_codes": ["math_share"],
                "total_score": None,
                "exam_scores": [],
                "funding_type": None,
                "study_form": None,
                "study_form_ambiguous": False,
                "admission_year": None,
                "admission_university_scope": None,
                "compare_with_any_other_direction": False,
                "unverified_answer": None,
            }
        elif "Write one concise" in system_prompt:
            result = {"question": "Какой вуз и программу сравнить?"}
        else:
            result = {"candidate_id": candidate.canonical_id}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(result)}}]},
        )

    provider = PolzaConversationAI(
        Settings(
            presentation_llm_enabled=False,
            presentation_llm_rate_limit_max=1,
            conversation_ai_rate_limit_max=4,
            polza_api_key="provider-secret-test-value",
        ),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    interpretation = provider.interpret(
        "Сравни бизнес-информатику по математике",
        current_intent=None,
        missing_slots=(),
        known_entities=(),
        allowed_metrics=("math_share",),
        rate_limit_key="private-owner-key",
    )
    question = provider.clarify(
        AssistantClarificationRequest(
            user_message="Сравни бизнес-информатику",
            intent=ConversationIntent.COMPARE_PROGRAMS,
            missing_slots=(ConversationSlot.ENTITY,),
            current_question="Какой вуз и программу сравнить?",
        ),
        rate_limit_key="private-owner-key",
    )
    selected = provider.select_catalog_candidate(
        "Сравни с любым другим направлением",
        candidates=(candidate,),
        rate_limit_key="private-owner-key",
    )
    repeated_interpretation = provider.interpret(
        "Ищи по любым вузам",
        current_intent=None,
        missing_slots=(),
        known_entities=(),
        allowed_metrics=("math_share",),
        rate_limit_key="private-owner-key",
    )

    assert len(observed) == 4
    assert all(str(request.url) == "https://polza.ai/api/v1/chat/completions" for request in observed)
    assert interpretation.intent is ConversationIntent.COMPARE_PROGRAMS
    assert interpretation.entities[0].query == "бизнес-информатика"
    assert interpretation.metric_codes == ("math_share",)
    assert "budget|paid|targeted|unknown" in observed[0].content.decode("utf-8")
    assert "modular monolith" in json.loads(observed[0].content)["messages"][0]["content"]
    assert "services/andromeda/docs/architecture.md" in observed[0].content.decode("utf-8")
    assert question == "Какой вуз и программу сравнить?"
    assert selected == candidate.canonical_id
    assert repeated_interpretation.intent is ConversationIntent.COMPARE_PROGRAMS
    for request in observed:
        assert request.headers["authorization"] == "Bearer provider-secret-test-value"
        content = request.content.decode("utf-8")
        assert "provider-secret-test-value" not in content
        assert "private-owner-key" not in content
        request_payload = json.loads(content)
        assert request_payload["temperature"] == 0
        assert request_payload["reasoning"] == {"enabled": False}


def test_polza_candidate_selection_rejects_ids_outside_the_real_catalog_set() -> None:
    candidate = AssistantEntityCandidate(
        entity_type=ResolutionEntityType.PROGRAM,
        canonical_id="program:bmstu:09.03.01-02",
        label="Каталожная программа",
    )

    provider = PolzaConversationAI(
        Settings(polza_api_key="provider-secret-test-value"),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"candidate_id":"program:invented"}'}}
                    ]
                },
            )
        ),
    )

    try:
        provider.select_catalog_candidate(
            "Сравни с другим",
            candidates=(candidate,),
            rate_limit_key="private-owner-key",
        )
    except ValueError as error:
        assert "outside the catalog candidates" in str(error)
    else:
        raise AssertionError("an ID outside the supplied real catalog candidates was accepted")


def test_polza_maps_only_explicit_russian_enum_aliases_to_typed_values() -> None:
    result = {
        "intent": "admission_search",
        "entities": [],
        "metric_codes": [],
        "total_score": None,
        "exam_scores": [],
        "funding_type": "бюджет",
        "study_form": None,
        "study_form_ambiguous": False,
        "admission_year": None,
        "admission_university_scope": "любым вузам",
        "compare_with_any_other_direction": False,
        "unverified_answer": None,
    }
    provider = PolzaConversationAI(
        Settings(polza_api_key="provider-secret-test-value"),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(result)}}]},
            )
        ),
    )

    interpretation = provider.interpret(
        "Ищи по любым вузам, на бюджет.",
        current_intent=ConversationIntent.ADMISSION_SEARCH,
        missing_slots=(ConversationSlot.UNIVERSITY_SCOPE,),
        known_entities=(),
        allowed_metrics=(),
        rate_limit_key="private-owner-key",
    )

    assert interpretation.funding_type is FundingType.BUDGET
    assert (
        interpretation.admission_university_scope
        is AdmissionUniversityScope.ANY_UNIVERSITY
    )


def test_polza_does_not_translate_unstated_enum_aliases() -> None:
    result = {
        "intent": "admission_search",
        "entities": [],
        "metric_codes": [],
        "total_score": None,
        "exam_scores": [],
        "funding_type": "бюджет",
        "study_form": None,
        "study_form_ambiguous": False,
        "admission_year": None,
        "admission_university_scope": None,
        "compare_with_any_other_direction": False,
        "unverified_answer": None,
    }
    provider = PolzaConversationAI(
        Settings(polza_api_key="provider-secret-test-value"),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(result)}}]},
            )
        ),
    )

    try:
        provider.interpret(
            "Куда поступать?",
            current_intent=None,
            missing_slots=(),
            known_entities=(),
            allowed_metrics=(),
            rate_limit_key="private-owner-key",
        )
    except ValueError as error:
        assert "enum" in str(error).lower() or "validation" in type(error).__name__.lower()
    else:
        raise AssertionError("a model-invented funding value was accepted")
