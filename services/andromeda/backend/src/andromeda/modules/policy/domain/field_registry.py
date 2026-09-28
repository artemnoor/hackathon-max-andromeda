"""Closed v1 selector-field registry and canonical value validation."""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from andromeda.modules.policy.contracts.rule_ast import (
    PolicyContextField,
    PolicySelectorAst,
    PolicySelectorNodeKind,
)


class SelectorValueKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DATE = "date"


_DATE_FIELDS = frozenset(
    {
        PolicyContextField.APPLICATION_START_DATE,
        PolicyContextField.APPLICATION_END_DATE,
        PolicyContextField.ENROLLMENT_START_DATE,
        PolicyContextField.ENROLLMENT_END_DATE,
    }
)

POLICY_SELECTOR_FIELD_REGISTRY: dict[PolicyContextField, SelectorValueKind] = {
    field: (
        SelectorValueKind.INTEGER
        if field is PolicyContextField.ADMISSION_YEAR
        else (
            SelectorValueKind.DATE
            if field in _DATE_FIELDS
            else SelectorValueKind.TEXT
        )
    )
    for field in PolicyContextField
}

_ID_PREFIXES: dict[PolicyContextField, str] = {
    PolicyContextField.REGULATOR_ID: "issuer:",
    PolicyContextField.UNIVERSITY_ID: "university:",
    PolicyContextField.CAMPUS_ID: "campus:",
    PolicyContextField.FACULTY_ID: "faculty:",
    PolicyContextField.DEPARTMENT_ID: "department:",
    PolicyContextField.DIRECTION_ID: "direction:",
    PolicyContextField.PROGRAM_ID: "program:",
    PolicyContextField.ADMISSION_CYCLE_ID: "admission-cycle:",
    PolicyContextField.OLYMPIAD_ID: "olympiad:",
    PolicyContextField.OLYMPIAD_PROFILE_ID: "olympiad-profile:",
    PolicyContextField.SUBJECT_ID: "subject:",
}


def validate_selector_ast(ast: PolicySelectorAst) -> None:
    """Validate each bounded scalar against the closed field registry."""
    for node in ast.nodes:
        if node.field is None or node.kind is PolicySelectorNodeKind.EXISTS:
            continue
        values = (node.value,) if node.kind is PolicySelectorNodeKind.EQUALS else node.values
        for value in values:
            validate_registered_context_value(node.field, value)


def validate_registered_context_value(field: PolicyContextField, value: object) -> None:
    """Validate a runtime context value with the same closed rules as stored selectors."""
    expected_kind = POLICY_SELECTOR_FIELD_REGISTRY.get(field)
    if expected_kind is None:
        raise ValueError("context field is not registered")
    if expected_kind is SelectorValueKind.INTEGER:
        if type(value) is not int or not 2000 <= value <= 2100:
            raise ValueError("admission_year requires an integer from 2000 to 2100")
        return
    if type(value) is not str:
        raise ValueError(f"{field.value} requires a text context value")
    if expected_kind is SelectorValueKind.DATE:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"{field.value} requires a canonical YYYY-MM-DD date") from exc
        return
    _validate_text_value(field, value)


def _validate_text_value(field: PolicyContextField, value: str) -> None:
    if not value.strip() or len(value) > 512:
        raise ValueError("selector text values must be non-empty and bounded")
    prefix = _ID_PREFIXES.get(field)
    if prefix is not None and (
        not value.startswith(prefix) or not _CANONICAL_ID.fullmatch(value)
    ):
        raise ValueError(f"{field.value} requires a canonical {prefix[:-1]} ID")
    if field is PolicyContextField.JURISDICTION and value not in {
        "federal",
        "regional",
        "university",
        "international",
    }:
        raise ValueError("jurisdiction selector value is unsupported")
    if field is PolicyContextField.ACADEMIC_YEAR:
        match = _ACADEMIC_YEAR.fullmatch(value)
        if match is None or int(match.group(2)) != int(match.group(1)) + 1:
            raise ValueError("academic_year selector must contain consecutive YYYY/YYYY years")
    if field in _SLUG_FIELDS and _SLUG.fullmatch(value) is None:
        raise ValueError(f"{field.value} must be a canonical lowercase slug")


_CANONICAL_ID = re.compile(r"^[a-z][a-z0-9-]*:[a-z0-9][a-z0-9._:-]{0,319}$")
_ACADEMIC_YEAR = re.compile(r"^([0-9]{4})/([0-9]{4})$")
_SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SLUG_FIELDS = frozenset(
    {
        PolicyContextField.EDUCATION_LEVEL,
        PolicyContextField.ADMISSION_ROUTE,
        PolicyContextField.COMPETITION_TYPE,
        PolicyContextField.APPLICANT_CATEGORY,
    }
)


__all__ = [
    "POLICY_SELECTOR_FIELD_REGISTRY",
    "SelectorValueKind",
    "validate_registered_context_value",
    "validate_selector_ast",
]
