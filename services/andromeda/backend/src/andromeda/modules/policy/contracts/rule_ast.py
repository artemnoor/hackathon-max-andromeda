"""Finite, versioned AST for selecting an owner-managed domain rule."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from andromeda.shared.contracts.base import ContractModel

SelectorNodeId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]
PolicySelectorScalar = StrictStr | StrictInt | StrictBool


class PolicyContextField(StrEnum):
    JURISDICTION = "jurisdiction"
    REGULATOR_ID = "regulator_id"
    UNIVERSITY_ID = "university_id"
    CAMPUS_ID = "campus_id"
    FACULTY_ID = "faculty_id"
    DEPARTMENT_ID = "department_id"
    EDUCATION_LEVEL = "education_level"
    DIRECTION_ID = "direction_id"
    PROGRAM_ID = "program_id"
    ADMISSION_CYCLE_ID = "admission_cycle_id"
    ADMISSION_YEAR = "admission_year"
    ACADEMIC_YEAR = "academic_year"
    APPLICATION_START_DATE = "application_start_date"
    APPLICATION_END_DATE = "application_end_date"
    ENROLLMENT_START_DATE = "enrollment_start_date"
    ENROLLMENT_END_DATE = "enrollment_end_date"
    ADMISSION_ROUTE = "admission_route"
    COMPETITION_TYPE = "competition_type"
    APPLICANT_CATEGORY = "applicant_category"
    OLYMPIAD_ID = "olympiad_id"
    OLYMPIAD_PROFILE_ID = "olympiad_profile_id"
    SUBJECT_ID = "subject_id"


class PolicySelectorNodeKind(StrEnum):
    ALL = "all"
    ANY = "any"
    EQUALS = "equals"
    IN = "in"
    EXISTS = "exists"


class PolicySelectorNode(ContractModel):
    node_id: SelectorNodeId
    parent_id: SelectorNodeId | None = None
    kind: PolicySelectorNodeKind
    field: PolicyContextField | None = None
    value: PolicySelectorScalar | None = None
    values: tuple[PolicySelectorScalar, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_node_shape(self) -> PolicySelectorNode:
        if self.kind in {PolicySelectorNodeKind.ALL, PolicySelectorNodeKind.ANY}:
            if self.field is not None or self.value is not None or self.values:
                raise ValueError("logical selector nodes cannot carry field values")
            return self
        if self.field is None:
            raise ValueError("selector leaf nodes require a registered context field")
        if self.kind is PolicySelectorNodeKind.EQUALS:
            if self.value is None or self.values:
                raise ValueError("equals selector requires one value")
            _validate_field_value(self.field, self.value)
        elif self.kind is PolicySelectorNodeKind.IN:
            if self.value is not None or not self.values:
                raise ValueError("in selector requires a bounded value list")
            for item in self.values:
                _validate_field_value(self.field, item)
            if len({(type(item), item) for item in self.values}) != len(self.values):
                raise ValueError("in selector values must be unique")
        elif self.kind is PolicySelectorNodeKind.EXISTS:
            if self.value is not None or self.values:
                raise ValueError("exists selector cannot carry comparison values")
        return self


class PolicySelectorAst(ContractModel):
    schema_version: Literal["policy-selector.v1"] = "policy-selector.v1"
    nodes: tuple[PolicySelectorNode, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_bounded_tree(self) -> PolicySelectorAst:
        by_id = {node.node_id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("selector node IDs must be unique")
        roots = tuple(node for node in self.nodes if node.parent_id is None)
        if len(roots) != 1:
            raise ValueError("selector AST must have exactly one root")
        children: dict[str, list[PolicySelectorNode]] = {node_id: [] for node_id in by_id}
        for node in self.nodes:
            if node.parent_id is None:
                continue
            parent = by_id.get(node.parent_id)
            if parent is None:
                raise ValueError("selector node references an unknown parent")
            if parent.kind not in {PolicySelectorNodeKind.ALL, PolicySelectorNodeKind.ANY}:
                raise ValueError("selector leaf nodes cannot have children")
            children[node.parent_id].append(node)
        for node in self.nodes:
            child_count = len(children[node.node_id])
            if node.kind in {PolicySelectorNodeKind.ALL, PolicySelectorNodeKind.ANY}:
                if not 2 <= child_count <= 32:
                    raise ValueError("logical selector nodes require between 2 and 32 children")
            elif child_count:
                raise ValueError("selector leaves cannot have children")

        visited: set[str] = set()
        stack: list[tuple[str, int, frozenset[str]]] = [
            (roots[0].node_id, 1, frozenset())
        ]
        while stack:
            node_id, depth, ancestors = stack.pop()
            if node_id in ancestors:
                raise ValueError("selector AST cannot contain cycles")
            if depth > 8:
                raise ValueError("selector AST depth cannot exceed 8")
            visited.add(node_id)
            next_ancestors = ancestors | {node_id}
            stack.extend(
                (child.node_id, depth + 1, next_ancestors)
                for child in children[node_id]
            )
        if visited != set(by_id):
            raise ValueError("all selector nodes must be reachable from the root")
        return self


def _validate_field_value(field: PolicyContextField, value: PolicySelectorScalar) -> None:
    if field is PolicyContextField.ADMISSION_YEAR:
        if type(value) is not int or not 2000 <= value <= 2100:
            raise ValueError("admission_year selector values must be integers from 2000 to 2100")
        return
    if type(value) is not str:
        raise ValueError(f"{field.value} selector values must be text")
    if not value.strip() or len(value) > 512:
        raise ValueError("selector text values must be non-empty and at most 512 characters")
    if field is PolicyContextField.JURISDICTION and value not in {
        "federal",
        "regional",
        "university",
        "international",
    }:
        raise ValueError("jurisdiction selector value is unsupported")
    if field is PolicyContextField.ACADEMIC_YEAR:
        if len(value) != 9 or value[4] != "/" or not value[:4].isdigit() or not value[5:].isdigit():
            raise ValueError("academic_year selector must use YYYY/YYYY format")
        if int(value[5:]) != int(value[:4]) + 1:
            raise ValueError("academic_year selector must contain consecutive years")
    if field in _NAMESPACED_ID_FIELDS and (
        ":" not in value or any(char.isspace() for char in value)
    ):
        raise ValueError(f"{field.value} selector values must be canonical namespaced IDs")


_NAMESPACED_ID_FIELDS = frozenset(
    {
        PolicyContextField.REGULATOR_ID,
        PolicyContextField.UNIVERSITY_ID,
        PolicyContextField.CAMPUS_ID,
        PolicyContextField.FACULTY_ID,
        PolicyContextField.DEPARTMENT_ID,
        PolicyContextField.DIRECTION_ID,
        PolicyContextField.PROGRAM_ID,
        PolicyContextField.ADMISSION_CYCLE_ID,
        PolicyContextField.OLYMPIAD_ID,
        PolicyContextField.OLYMPIAD_PROFILE_ID,
        PolicyContextField.SUBJECT_ID,
    }
)


__all__ = [
    "PolicyContextField",
    "PolicySelectorAst",
    "PolicySelectorNode",
    "PolicySelectorNodeKind",
    "PolicySelectorScalar",
    "SelectorNodeId",
]
