"""Andromeda-owned serializers for upstream Jev evaluation tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from andromeda.infrastructure.jev.question_registry import (
    QuestionRegistry,
    QuestionRegistryExport,
)


class EvaluationExportError(ValueError):
    """Raised when registry/corpus data cannot be exported safely."""


@dataclass(frozen=True, slots=True)
class JevcalExportBundle:
    """Native jevcal inputs plus provenance owned by the exporter."""

    questions: dict[str, dict[str, object]]
    rows: tuple[dict[str, object], ...]
    registry_hash: str


def build_jevcal_bundle(
    registry: QuestionRegistry,
    source_rows: tuple[dict[str, object], ...],
    *,
    definition_ids: tuple[str, ...] | None = None,
) -> JevcalExportBundle:
    """Convert validated Andromeda rows to jevcal ``questions``/``labels`` input."""

    exports = registry.export()
    by_id = {definition.definition_id: definition for definition in exports}
    if len(by_id) != len(exports):
        raise EvaluationExportError("registry export contains duplicate definition IDs")

    selected_ids = tuple(definition_ids) if definition_ids is not None else tuple(by_id)
    if not selected_ids or len(selected_ids) != len(set(selected_ids)):
        raise EvaluationExportError(
            "selected definition IDs must be non-empty and unique"
        )
    unknown_ids = set(selected_ids) - set(by_id)
    if unknown_ids:
        raise EvaluationExportError(
            "unknown selected definition IDs: " + ", ".join(sorted(unknown_ids))
        )

    labels_by_definition: dict[str, set[str]] = {
        definition_id: set() for definition_id in selected_ids
    }
    native_rows: list[dict[str, object]] = []
    seen_case_ids: set[str] = set()
    for row in source_rows:
        case_id = _required_string(row, "case_id")
        if case_id in seen_case_ids:
            raise EvaluationExportError(f"duplicate case ID: {case_id}")
        seen_case_ids.add(case_id)
        definition_id = _required_string(row, "definition_id")
        if definition_id not in labels_by_definition:
            raise EvaluationExportError(
                f"case {case_id} is outside the selected calibration definitions"
            )
        definition = by_id.get(definition_id)
        if definition is None:
            raise EvaluationExportError(f"unknown definition ID: {definition_id}")
        if row.get("definition_version") != definition.definition_version:
            raise EvaluationExportError(f"definition version mismatch: {case_id}")
        split = _required_string(row, "split")
        input_data = row.get("input")
        expected = row.get("expected")
        if not isinstance(input_data, dict) or not isinstance(expected, dict):
            raise EvaluationExportError(
                f"case must contain mapping input/expected: {case_id}"
            )
        label = _label_for(definition, input_data, expected)
        labels_by_definition[definition_id].add(label)
        if definition.kind == "metric":
            metric_candidates = input_data.get("candidates")
            if isinstance(metric_candidates, list):
                labels_by_definition[definition_id].update(
                    value
                    for value in metric_candidates
                    if isinstance(value, str) and value
                )
            labels_by_definition[definition_id].add("unresolved")
        elif definition.kind == "entity_resolution":
            entity_candidates = input_data.get("candidates")
            if isinstance(entity_candidates, list):
                for candidate in entity_candidates:
                    if isinstance(candidate, dict):
                        candidate_id = candidate.get("candidate_id")
                        if isinstance(candidate_id, str) and candidate_id:
                            labels_by_definition[definition_id].add(candidate_id)
            labels_by_definition[definition_id].add("unresolved")
        native_rows.append(
            {
                "id": case_id,
                "state": input_data,
                "labels": {definition_id: label},
                "andromeda": {
                    "definition_id": definition_id,
                    "definition_version": definition.definition_version,
                    "split": split,
                },
            }
        )

    questions = {
        definition_id: _question_for(
            by_id[definition_id], labels_by_definition[definition_id]
        )
        for definition_id in selected_ids
    }
    return JevcalExportBundle(
        questions=questions,
        rows=tuple(native_rows),
        registry_hash=registry.content_hash(),
    )


def _question_for(
    definition: QuestionRegistryExport, observed_labels: set[str]
) -> dict[str, object]:
    criteria: dict[str, str] = {}
    if definition.kind == "intent":
        criteria = {
            option["code"]: option["description"] for option in definition.options
        }
    elif definition.kind == "metric":
        criteria = {value: value for value in sorted(observed_labels) if value}
    elif definition.kind == "next_action" or definition.kind == "presentation":
        criteria = {value: value for value in definition.output_allowed_values}
    elif definition.kind in {"semantic_feature", "entity_resolution"}:
        criteria = {value: value for value in sorted(observed_labels) if value}
    if len(criteria) < 2:
        raise EvaluationExportError(
            f"definition {definition.definition_id} needs at least two native choice criteria"
        )
    return {
        "type": "choice",
        "instructions": definition.instructions,
        "criteria": criteria,
    }


def _label_for(
    definition: QuestionRegistryExport,
    input_data: dict[str, object],
    expected: dict[str, object],
) -> str:
    if definition.kind == "intent":
        return _expected_string(expected, "intent", definition.definition_id)
    if definition.kind == "metric":
        value = expected.get("metric_code")
        if value is None:
            return "unresolved"
        return _string_value(value, definition.definition_id)
    if definition.kind == "next_action":
        return _expected_string(expected, "action", definition.definition_id)
    if definition.kind == "presentation":
        return _expected_string(expected, "response_format", definition.definition_id)
    if definition.kind == "entity_resolution":
        value = expected.get("candidate_id")
        if value is None:
            return "unresolved"
        candidate_id = _string_value(value, definition.definition_id)
        candidates = input_data.get("candidates")
        if not isinstance(candidates, list) or not any(
            isinstance(candidate, dict)
            and candidate.get("candidate_id") == candidate_id
            for candidate in candidates
        ):
            raise EvaluationExportError(
                f"entity-resolution label is outside its bounded candidate set: {definition.definition_id}"
            )
        return candidate_id
    values = expected.get("values")
    if isinstance(values, list) and values:
        first = values[0]
        feature_code = first.get("feature_code") if isinstance(first, dict) else None
        if isinstance(feature_code, str):
            return feature_code
    if expected.get("review_status") == "review_required":
        return "review_required"
    feature_codes = input_data.get("feature_codes")
    if (
        isinstance(feature_codes, list)
        and feature_codes
        and isinstance(feature_codes[0], str)
    ):
        return feature_codes[0]
    raise EvaluationExportError(
        f"semantic feature label is missing: {definition.definition_id}"
    )


def _expected_string(expected: dict[str, object], key: str, definition_id: str) -> str:
    value = expected.get(key)
    return _string_value(value, definition_id)


def _required_string(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise EvaluationExportError(f"{key} must be a non-empty string")
    return value


def _string_value(value: Any, definition_id: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationExportError(f"label is invalid for {definition_id}")
    return value


__all__ = ["EvaluationExportError", "JevcalExportBundle", "build_jevcal_bundle"]
