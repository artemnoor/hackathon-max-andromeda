from __future__ import annotations

from pathlib import Path

import pytest

from andromeda.infrastructure.jev.question_registry import (
    QuestionRegistry,
    QuestionRegistryError,
)
from andromeda.modules.conversation.contracts.decision_definitions import (
    DecisionDefinitionKind,
)

REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "jev"
    / "question-definitions.v1.yaml"
)
ADMISSION_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "jev"
    / "question-definitions.admission.v1.yaml"
)


def test_loads_versioned_registry_artifact() -> None:
    registry = QuestionRegistry.from_file(REGISTRY_PATH)

    assert len(registry.all()) == 5
    assert registry.get("metric.v1").operation == "resolve_metric"
    assert (
        registry.for_operation("choose_next_action").kind
        is DecisionDefinitionKind.NEXT_ACTION
    )


def test_admission_entity_resolution_has_its_own_versioned_calibration_definition() -> (
    None
):
    registry = QuestionRegistry.from_file(ADMISSION_REGISTRY_PATH)

    definition = registry.for_operation("resolve_olympiad_profile")

    assert definition.definition_id == "olympiad-profile-resolution.v1"
    assert definition.kind is DecisionDefinitionKind.ENTITY_RESOLUTION
    assert definition.version == "olympiad-profile-resolution-definition.v1"
    assert definition.pii_policy.value == "sanitized"
    assert definition.output_schema.allowed_values == ("unresolved",)


def test_exports_stable_vendor_neutral_projection() -> None:
    registry = QuestionRegistry.from_file(REGISTRY_PATH)

    exported = registry.export()

    assert len(exported) == 5
    assert exported[0].registry_hash == registry.content_hash()
    assert exported[0].as_dict()["output_schema"] == {
        "fields": ["intent", "confidence"],
        "allowed_values": [
            "catalog_search",
            "comparison",
            "admission_search",
            "recommendation",
            "unknown",
        ],
        "additional_properties": False,
    }
    assert exported[0].as_dict()["options"][0]["code"] == "catalog_search"


def test_export_keeps_definition_lookup_fail_closed() -> None:
    registry = QuestionRegistry.from_file(REGISTRY_PATH)

    with pytest.raises(QuestionRegistryError, match="unknown decision definition"):
        registry.export_definition("missing.v1")


def test_unknown_definition_and_operation_fail_closed() -> None:
    registry = QuestionRegistry.from_file(REGISTRY_PATH)

    with pytest.raises(QuestionRegistryError, match="unknown decision definition"):
        registry.get("missing.v1")
    with pytest.raises(QuestionRegistryError, match="unknown decision operation"):
        registry.for_operation("execute_sql")


def test_duplicate_ids_and_operations_are_rejected() -> None:
    document = {
        "definitions": [
            registry_definition("duplicate.v1", "resolve_intent"),
            registry_definition("duplicate.v1", "resolve_metric"),
        ]
    }

    with pytest.raises(QuestionRegistryError, match="duplicate definition id"):
        QuestionRegistry.from_document(document)


def test_duplicate_operations_are_rejected() -> None:
    document = {
        "definitions": [
            registry_definition("intent.v1", "resolve_intent"),
            registry_definition("metric.v1", "resolve_intent"),
        ]
    }

    with pytest.raises(QuestionRegistryError, match="duplicate operation"):
        QuestionRegistry.from_document(document)


def test_malformed_yaml_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "broken.yaml"
    artifact.write_text("definitions: [", encoding="utf-8")

    with pytest.raises(QuestionRegistryError, match="invalid question registry YAML"):
        QuestionRegistry.from_file(artifact)


def test_invalid_definition_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "invalid.yaml"
    artifact.write_text(
        "definitions:\n  - definition_id: broken\n    kind: unsupported\n",
        encoding="utf-8",
    )

    with pytest.raises(QuestionRegistryError, match="invalid question definition"):
        QuestionRegistry.from_file(artifact)


def registry_definition(definition_id: str, operation: str) -> dict[str, object]:
    return {
        "definition_id": definition_id,
        "kind": "intent",
        "operation": operation,
        "version": "test.v1",
        "instructions": "test",
        "output_schema": {"fields": ["value"], "additional_properties": False},
        "deterministic_fallback": "rule",
        "timeout_class": "interactive",
        "pii_policy": "sanitized",
        "evaluation_dataset_key": "test.v1",
    }
