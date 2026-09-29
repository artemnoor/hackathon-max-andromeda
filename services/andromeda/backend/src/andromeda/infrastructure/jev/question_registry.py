"""Validated, immutable registry for shared decision definitions."""

from __future__ import annotations

import logging
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from andromeda.modules.conversation.contracts.decision_definitions import (
    DecisionDefinition,
    DecisionDefinitionKind,
    DecisionOption,
    DecisionOutputSchema,
    DecisionPiiPolicy,
    DecisionTimeoutClass,
    QuestionRegistryPort,
)

logger = logging.getLogger("andromeda.infrastructure.jev.question_registry")


class QuestionRegistryError(ValueError):
    """Raised when the shared decision-definition artifact is invalid."""


@dataclass(frozen=True, slots=True)
class QuestionRegistryExport:
    """Vendor-neutral immutable projection consumed by external tool adapters."""

    definition_id: str
    definition_version: str
    kind: str
    operation: str
    instructions: str
    criteria: tuple[str, ...]
    options: tuple[Mapping[str, str], ...]
    input_fields: tuple[str, ...]
    output_fields: tuple[str, ...]
    output_allowed_values: tuple[str, ...]
    output_additional_properties: bool
    deterministic_fallback: str
    timeout_class: str
    max_input_chars: int
    pii_policy: str
    evidence_required: bool
    evaluation_dataset_key: str
    registry_hash: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe mapping for tool-specific serializers."""

        return {
            "definition_id": self.definition_id,
            "definition_version": self.definition_version,
            "kind": self.kind,
            "operation": self.operation,
            "instructions": self.instructions,
            "criteria": list(self.criteria),
            "options": [dict(option) for option in self.options],
            "input_fields": list(self.input_fields),
            "output_schema": {
                "fields": list(self.output_fields),
                "allowed_values": list(self.output_allowed_values),
                "additional_properties": self.output_additional_properties,
            },
            "deterministic_fallback": self.deterministic_fallback,
            "timeout_class": self.timeout_class,
            "max_input_chars": self.max_input_chars,
            "pii_policy": self.pii_policy,
            "evidence_required": self.evidence_required,
            "evaluation_dataset_key": self.evaluation_dataset_key,
            "registry_hash": self.registry_hash,
        }


class QuestionRegistry(QuestionRegistryPort):
    """Immutable registry with fail-closed lookup semantics."""

    def __init__(self, definitions: Sequence[DecisionDefinition]) -> None:
        if not definitions:
            raise QuestionRegistryError("question registry must contain at least one definition")

        by_id: dict[str, DecisionDefinition] = {}
        by_operation: dict[str, DecisionDefinition] = {}
        for definition in definitions:
            if definition.definition_id in by_id:
                raise QuestionRegistryError(f"duplicate definition id: {definition.definition_id}")
            if definition.operation in by_operation:
                raise QuestionRegistryError(f"duplicate operation: {definition.operation}")
            by_id[definition.definition_id] = definition
            by_operation[definition.operation] = definition

        self._by_id = MappingProxyType(by_id)
        self._by_operation = MappingProxyType(by_operation)
        self._definitions = tuple(definitions)
        logger.info("question_registry_loaded definitions=%s", len(self._definitions))

    @classmethod
    def from_file(cls, path: str | Path) -> QuestionRegistry:
        artifact_path = Path(path)
        logger.debug("question_registry_load_started path=%s", artifact_path)
        try:
            with artifact_path.open("r", encoding="utf-8") as stream:
                document = yaml.safe_load(stream)
        except FileNotFoundError as exc:
            logger.error("question_registry_load_failed reason=missing_file path=%s", artifact_path)
            raise QuestionRegistryError(f"question registry file does not exist: {artifact_path}") from exc
        except yaml.YAMLError as exc:
            logger.error("question_registry_load_failed reason=invalid_yaml path=%s", artifact_path)
            raise QuestionRegistryError(f"invalid question registry YAML: {artifact_path}") from exc
        return cls.from_document(document, source=str(artifact_path))

    @classmethod
    def from_document(cls, document: object, *, source: str = "memory") -> QuestionRegistry:
        if not isinstance(document, Mapping):
            raise QuestionRegistryError(f"question registry document must be a mapping: {source}")
        definitions = document.get("definitions")
        if not isinstance(definitions, Sequence) or isinstance(definitions, (str, bytes)):
            raise QuestionRegistryError(f"question registry definitions must be a list: {source}")

        parsed: list[DecisionDefinition] = []
        for index, raw in enumerate(definitions):
            if not isinstance(raw, Mapping):
                raise QuestionRegistryError(f"definition {index} must be a mapping: {source}")
            try:
                normalized = cls._normalize_definition(raw)
                parsed.append(DecisionDefinition.model_validate(normalized, strict=True))
            except (TypeError, ValueError, KeyError) as exc:
                logger.error("question_definition_rejected source=%s index=%s", source, index)
                raise QuestionRegistryError(f"invalid question definition {index}: {source}") from exc

        return cls(parsed)

    @staticmethod
    def _normalize_definition(raw: Mapping[str, Any]) -> dict[str, Any]:
        """Convert YAML's scalar/list representation to strict contract values."""

        normalized = dict(raw)
        normalized["kind"] = DecisionDefinitionKind(normalized["kind"])
        normalized["timeout_class"] = DecisionTimeoutClass(normalized["timeout_class"])
        normalized["pii_policy"] = DecisionPiiPolicy(normalized["pii_policy"])

        for field_name in ("criteria", "input_fields"):
            normalized[field_name] = QuestionRegistry._as_tuple(normalized.get(field_name, ()))

        options = normalized.get("options", ())
        normalized["options"] = tuple(
            option
            if isinstance(option, DecisionOption)
            else DecisionOption.model_validate(
                dict(QuestionRegistry._as_mapping(option)), strict=False
            )
            for option in QuestionRegistry._as_sequence(options)
        )

        output_schema = normalized["output_schema"]
        if not isinstance(output_schema, DecisionOutputSchema):
            if not isinstance(output_schema, Mapping):
                raise TypeError("output_schema must be a mapping")
            output_data = dict(output_schema)
            output_data["fields"] = QuestionRegistry._as_tuple(output_data.get("fields", ()))
            output_data["allowed_values"] = QuestionRegistry._as_tuple(
                output_data.get("allowed_values", ())
            )
            output_schema = DecisionOutputSchema.model_validate(output_data, strict=False)
        normalized["output_schema"] = output_schema
        return normalized

    @staticmethod
    def _as_sequence(value: object) -> Sequence[object]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise TypeError("registry field must be a sequence")
        return value

    @staticmethod
    def _as_mapping(value: object) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("registry option must be a mapping")
        return value

    @staticmethod
    def _as_tuple(value: object) -> tuple[object, ...]:
        return tuple(QuestionRegistry._as_sequence(value))

    def get(self, definition_id: str) -> DecisionDefinition:
        try:
            return self._by_id[definition_id]
        except KeyError as exc:
            logger.warning("question_definition_not_found definition_id=%s", definition_id)
            raise QuestionRegistryError(f"unknown decision definition: {definition_id}") from exc

    def for_operation(self, operation: str) -> DecisionDefinition:
        try:
            return self._by_operation[operation]
        except KeyError as exc:
            logger.warning("question_operation_not_found operation=%s", operation)
            raise QuestionRegistryError(f"unknown decision operation: {operation}") from exc

    def all(self) -> tuple[DecisionDefinition, ...]:
        return self._definitions


    def export(self) -> tuple[QuestionRegistryExport, ...]:
        """Expose one stable projection for Jev ecosystem adapters."""

        registry_hash = self.content_hash()
        exports = tuple(self._export_definition(definition, registry_hash) for definition in self._definitions)
        logger.debug(
            "question_registry_exported definitions=%s registry_hash=%s",
            len(exports),
            registry_hash,
        )
        return exports

    def export_definition(self, definition_id: str) -> QuestionRegistryExport:
        """Export one definition while retaining registry-wide identity."""

        definition = self.get(definition_id)
        registry_hash = self.content_hash()
        return self._export_definition(definition, registry_hash)

    def content_hash(self) -> str:
        """Return the deterministic hash of the validated registry projection."""

        canonical = [definition.model_dump(mode="json") for definition in self._definitions]
        payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _export_definition(
        definition: DecisionDefinition, registry_hash: str
    ) -> QuestionRegistryExport:
        return QuestionRegistryExport(
            definition_id=definition.definition_id,
            definition_version=definition.version,
            kind=definition.kind.value,
            operation=definition.operation,
            instructions=definition.instructions,
            criteria=definition.criteria,
            options=tuple(
                MappingProxyType({"code": option.code, "description": option.description})
                for option in definition.options
            ),
            input_fields=definition.input_fields,
            output_fields=definition.output_schema.fields,
            output_allowed_values=definition.output_schema.allowed_values,
            output_additional_properties=definition.output_schema.additional_properties,
            deterministic_fallback=definition.deterministic_fallback,
            timeout_class=definition.timeout_class.value,
            max_input_chars=definition.max_input_chars,
            pii_policy=definition.pii_policy.value,
            evidence_required=definition.evidence_required,
            evaluation_dataset_key=definition.evaluation_dataset_key,
            registry_hash=registry_hash,
        )


__all__ = ["QuestionRegistry", "QuestionRegistryError", "QuestionRegistryExport"]
