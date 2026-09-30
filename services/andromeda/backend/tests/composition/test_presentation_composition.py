from __future__ import annotations

from sqlalchemy import create_engine

from andromeda.composition.container import build_container
from andromeda.infrastructure.adapters.polza_conversation_ai import PolzaConversationAI
from andromeda.infrastructure.adapters.polza_naturalizer import PolzaNaturalizer
from andromeda.infrastructure.config.settings import Settings


def test_missing_optional_provider_key_keeps_container_deterministic() -> None:
    engine = create_engine("sqlite://")
    try:
        container = build_container(
            engine,
            Settings(presentation_llm_enabled=True, polza_api_key=None),
        )

        assert container.presentation_naturalizer() is None
    finally:
        engine.dispose()


def test_conversation_ai_uses_configured_key_independently_of_prose_naturalization() -> None:
    engine = create_engine("sqlite://")
    try:
        disabled = build_container(
            engine,
            Settings(
                presentation_llm_enabled=False,
                polza_api_key="test-provider-secret",
            ),
        )
        enabled = build_container(
            engine,
            Settings(
                presentation_llm_enabled=True,
                polza_api_key="test-provider-secret",
            ),
        )

        assert disabled.presentation_naturalizer() is None
        assert isinstance(disabled.conversation_ai(), PolzaConversationAI)
        assert isinstance(enabled.presentation_naturalizer(), PolzaNaturalizer)
        assert isinstance(enabled.conversation_ai(), PolzaConversationAI)
    finally:
        engine.dispose()
