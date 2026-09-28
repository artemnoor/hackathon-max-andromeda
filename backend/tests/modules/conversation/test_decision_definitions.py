from __future__ import annotations

import pytest
from pydantic import ValidationError

from andromeda.modules.conversation.contracts.decision_definitions import (
    DecisionDefinition,
    DecisionDefinitionKind,
    DecisionOption,
    DecisionOutputSchema,
    DecisionPiiPolicy,
    DecisionTimeoutClass,
)


def make_definition(*, definition_id: str = "intent.v1") -> DecisionDefinition:
    return DecisionDefinition(
        definition_id=definition_id,
        kind=DecisionDefinitionKind.INTENT,
        operation="resolve_intent",
        version="intent-definition.v1",
        instructions="Resolve a supported intent.",
        criteria=("return one supported code",),
        options=(DecisionOption(code="unknown", description="Unknown request"),),
        input_fields=("text",),
        output_schema=DecisionOutputSchema(
            fields=("intent", "confidence"),
            allowed_values=("unknown",),
        ),
        deterministic_fallback="rule_based_intent",
        timeout_class=DecisionTimeoutClass.INTERACTIVE,
        pii_policy=DecisionPiiPolicy.SANITIZED,
        evidence_required=False,
        evaluation_dataset_key="decision.intent.v1",
    )


def test_definition_is_typed_and_versioned() -> None:
    definition = make_definition()

    assert definition.definition_id == "intent.v1"
    assert definition.version == "intent-definition.v1"
    assert definition.kind is DecisionDefinitionKind.INTENT
    assert definition.output_schema.additional_properties is False


def test_definition_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DecisionDefinition.model_validate(
            {
                **make_definition().model_dump(),
                "provider_prompt": "vendor-specific",
            },
            strict=True,
        )


@pytest.mark.parametrize("definition_id", ["", "Intent V1", "intent/v1", "intent v1"])
def test_definition_rejects_unstable_ids(definition_id: str) -> None:
    with pytest.raises(ValidationError):
        make_definition(definition_id=definition_id)

