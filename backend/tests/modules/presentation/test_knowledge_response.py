from __future__ import annotations

import pytest
from pydantic import HttpUrl, ValidationError

from andromeda.modules.presentation.contracts.knowledge_response import (
    KnowledgeAnswerState,
    KnowledgeResponseSection,
    ResponseActionability,
    ResponseEvidenceReference,
    ResponseFact,
    ResponseMode,
    ResponseUncertainty,
)
from andromeda.modules.presentation.contracts.verbalization import (
    PresentationSectionKind,
    ResponseVerbalizationPlan,
    ResponseVerbalizationRequest,
)
from andromeda.modules.presentation.services.knowledge_response import (
    KnowledgeResponseRenderer,
)


def test_knowledge_response_keeps_unknown_actionability_explicit() -> None:
    response = KnowledgeResponseSection(
        status=KnowledgeAnswerState.NO_EVIDENCE,
        actionability=ResponseActionability.UNCERTAIN,
    )

    assert response.known_facts == ()
    assert response.impact_delta == ()
    assert response.actionability is ResponseActionability.UNCERTAIN


def test_constrained_verbalizer_can_only_reorder_safe_section_references() -> None:
    response = KnowledgeResponseSection(
        status=KnowledgeAnswerState.INSUFFICIENT_DATA,
        actionability=ResponseActionability.UNCERTAIN,
        known_facts=(ResponseFact(label="Дата публикации", value="01.12.2027"),),
        impact_delta=(ResponseFact(label="Баллы", value="30", unit="баллов"),),
        uncertainties=(ResponseUncertainty.DOMAIN_RESULT_UNAVAILABLE,),
    )
    original_payload = response.model_dump(mode="json")
    deterministic = KnowledgeResponseRenderer().render(response)

    class ReorderingVerbalizer:
        def plan(
            self,
            request: ResponseVerbalizationRequest,
        ) -> ResponseVerbalizationPlan:
            assert all(hasattr(item, "section_id") for item in request.sections)
            request_json = request.model_dump_json()
            assert "Баллы" not in request_json
            assert '"value"' not in request_json
            assert request.sections[0].kind is PresentationSectionKind.STATUS
            by_kind = {item.kind: item.section_id for item in request.sections}
            return ResponseVerbalizationPlan(
                section_order=(
                    request.sections[0].section_id,
                    by_kind[PresentationSectionKind.UNCERTAINTY],
                    by_kind[PresentationSectionKind.IMPACT],
                    by_kind[PresentationSectionKind.FACTS],
                )
            )

    verbalized = KnowledgeResponseRenderer(ReorderingVerbalizer()).render(response)

    assert deterministic.response_mode is ResponseMode.DETERMINISTIC
    assert verbalized.response_mode is ResponseMode.SOURCE_BACKED_VERBALIZATION
    assert deterministic.text != verbalized.text
    assert verbalized.text.index("Что пока неизвестно") < verbalized.text.index(
        "Что меняется"
    )
    assert "Дата публикации: 01.12.2027." in deterministic.text
    assert response.model_dump(mode="json") == original_payload


def test_renderer_bounds_text_and_keeps_full_typed_data() -> None:
    response = KnowledgeResponseSection(
        status=KnowledgeAnswerState.SOURCE_ASSERTION,
        actionability=ResponseActionability.INFORMATIONAL,
        known_facts=tuple(
            ResponseFact(label=f"Факт {index}", value="x" * 512) for index in range(100)
        ),
        impact_delta=tuple(
            ResponseFact(label=f"Изменение {index}", value="y" * 512)
            for index in range(20)
        ),
    )

    rendered = KnowledgeResponseRenderer().render(response)

    assert len(rendered.text) <= 20_000
    assert "Текст сокращён по размеру" in rendered.text
    assert len(response.known_facts) == 100


def test_unverified_fallback_is_explicit_and_restricted_to_outside_coverage() -> None:
    response = KnowledgeResponseSection(
        status=KnowledgeAnswerState.OUTSIDE_COVERAGE,
        actionability=ResponseActionability.UNCERTAIN,
        uncertainties=(ResponseUncertainty.OUTSIDE_KNOWLEDGE_COVERAGE,),
    )

    rendered = KnowledgeResponseRenderer().render(
        response,
        unverified_fallback=True,
    )

    assert rendered.response_mode is ResponseMode.UNVERIFIED_FALLBACK
    assert "вне проверенного покрытия" in rendered.text
    assert "общий ответ не предоставлен" in rendered.text

    verified = KnowledgeResponseSection(
        status=KnowledgeAnswerState.POLICY_RESOLVED,
        actionability=ResponseActionability.INFORMATIONAL,
    )
    with pytest.raises(ValueError, match="outside coverage"):
        KnowledgeResponseRenderer().render(verified, unverified_fallback=True)


def test_invalid_or_unavailable_verbalizer_falls_back_without_added_content() -> None:
    response = KnowledgeResponseSection(
        status=KnowledgeAnswerState.NO_EVIDENCE,
        actionability=ResponseActionability.UNCERTAIN,
        uncertainties=(ResponseUncertainty.NO_SOURCE_ASSERTION_FOUND,),
    )

    class InvalidVerbalizer:
        def plan(
            self,
            request: ResponseVerbalizationRequest,
        ) -> ResponseVerbalizationPlan:
            return ResponseVerbalizationPlan(section_order=("section:" + "f" * 64,))

    rendered = KnowledgeResponseRenderer(InvalidVerbalizer()).render(response)

    assert rendered.response_mode is ResponseMode.DETERMINISTIC
    assert "не доказывает отсутствие правила" in rendered.text
    assert "f" * 64 not in rendered.text


def test_verbalizer_timeout_uses_deterministic_response() -> None:
    response = KnowledgeResponseSection(
        status=KnowledgeAnswerState.NO_EVIDENCE,
        actionability=ResponseActionability.UNCERTAIN,
        uncertainties=(ResponseUncertainty.NO_SOURCE_ASSERTION_FOUND,),
    )

    class TimeoutVerbalizer:
        def plan(
            self,
            request: ResponseVerbalizationRequest,
        ) -> ResponseVerbalizationPlan:
            del request
            raise TimeoutError

    rendered = KnowledgeResponseRenderer(TimeoutVerbalizer()).render(response)

    assert rendered.response_mode is ResponseMode.DETERMINISTIC
    assert "не доказывает отсутствие правила" in rendered.text


@pytest.mark.parametrize(
    "url",
    (
        "http://ministry.example/rules.pdf",
        "https://user@ministry.example/rules.pdf",
        "https://ministry.example/rules.pdf?token=secret",
        "https://ministry.example/rules.pdf#page=4",
    ),
)
def test_public_evidence_reference_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        ResponseEvidenceReference(
            source_reference="source:ministry",
            observation_reference="source-observation:" + "a" * 32,
            snapshot_sha256="a" * 64,
            url=HttpUrl(url),
        )
