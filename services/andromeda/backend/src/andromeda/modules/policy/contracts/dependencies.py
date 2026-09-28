"""Typed dependency edges exposed by policy revisions without a generic graph store."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .applicability import PolicySelection
from .rule import DomainRuleRef, PolicyRuleRelationKind, PolicyRuleRevision, PolicyScope

PolicyDependencyEdgeId = Annotated[str, StringConstraints(pattern=r"^policy-dependency:[a-f0-9]{64}$")]


class PolicyDependencyKind(StrEnum):
    APPLIES_TO = "applies_to"
    EXCEPTION_TO = "exception_to"
    AUTHORIZED_EXCEPTION_TO = "authorized_exception_to"
    OVERRIDES = "overrides"
    SUPERSEDES = "supersedes"
    AMENDS = "amends"
    IMPLEMENTS = "implements"
    REQUIRES = "requires"


class PolicyDependencyNodeKind(StrEnum):
    POLICY_RULE = "policy_rule"
    DOMAIN_RULE = "domain_rule"
    SCOPE = "scope"


class PolicyDependencyNode(ContractModel):
    kind: PolicyDependencyNodeKind
    object_id: Annotated[str, StringConstraints(min_length=1, max_length=320)]
    revision: int | None = Field(default=None, strict=True, ge=1, le=2_147_483_647)
    content_hash: SourceHash | None = None
    owner_module: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def shape_matches_kind(self) -> PolicyDependencyNode:
        if self.kind is PolicyDependencyNodeKind.POLICY_RULE:
            if not self.object_id.startswith("policy-rule:") or self.revision is None or self.content_hash is None:
                raise ValueError("policy-rule dependency nodes require exact revision and content hash")
            if self.owner_module is not None:
                raise ValueError("policy-rule dependency nodes do not carry a domain owner")
        elif self.kind is PolicyDependencyNodeKind.DOMAIN_RULE:
            if self.revision is None or self.content_hash is not None or self.owner_module is None:
                raise ValueError("domain-rule nodes require owner and exact owner revision")
        elif self.revision is not None or self.content_hash is not None or self.owner_module is not None:
            raise ValueError("scope dependency nodes are canonical targets without revisions")
        if any(char.isspace() for char in self.object_id):
            raise ValueError("dependency node IDs cannot contain whitespace")
        return self

    def identity(self) -> tuple[str, str, int | None, str | None, str | None]:
        return self.kind.value, self.object_id, self.revision, self.content_hash, self.owner_module


class PolicyDependencyEdge(ContractModel):
    edge_id: PolicyDependencyEdgeId
    kind: PolicyDependencyKind
    source: PolicyDependencyNode
    target: PolicyDependencyNode
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def typed_endpoints_and_identity(self) -> PolicyDependencyEdge:
        if self.source == self.target:
            raise ValueError("policy dependency edge cannot be a self edge")
        if self.kind is PolicyDependencyKind.APPLIES_TO and self.target.kind is not PolicyDependencyNodeKind.SCOPE:
            raise ValueError("APPLIES_TO must target a typed policy scope")
        if self.kind in {
            PolicyDependencyKind.EXCEPTION_TO,
            PolicyDependencyKind.AUTHORIZED_EXCEPTION_TO,
            PolicyDependencyKind.OVERRIDES,
            PolicyDependencyKind.SUPERSEDES,
            PolicyDependencyKind.AMENDS,
        } and (self.source.kind is not PolicyDependencyNodeKind.POLICY_RULE or self.target.kind is not PolicyDependencyNodeKind.POLICY_RULE):
            raise ValueError("precedence dependency edges must connect exact policy revisions")
        if self.kind is PolicyDependencyKind.IMPLEMENTS and (
            self.source.kind is not PolicyDependencyNodeKind.POLICY_RULE
            or self.target.kind is not PolicyDependencyNodeKind.DOMAIN_RULE
        ):
            raise ValueError("IMPLEMENTS must connect a policy revision to its domain-owned rule")
        if self.edge_id != policy_dependency_edge_id(self.kind, self.source, self.target, self.evidence):
            raise ValueError("policy dependency edge ID does not match its typed content")
        return self


class PolicyDependencyTraversalRequest(ContractModel):
    root: PolicyDependencyNode
    max_depth: int = Field(default=8, strict=True, ge=1, le=8)
    max_nodes: int = Field(default=1000, strict=True, ge=1, le=1000)


class PolicyDependencyTraversal(ContractModel):
    root: PolicyDependencyNode
    nodes: tuple[PolicyDependencyNode, ...] = Field(max_length=1000)
    edges: tuple[PolicyDependencyEdgeId, ...] = Field(max_length=10000)
    cycles: tuple[PolicyDependencyEdgeId, ...] = Field(default=(), max_length=1000)
    truncated: bool = False
    maximum_depth: int = Field(ge=0, le=8)


def policy_dependency_edge_id(
    kind: PolicyDependencyKind,
    source: PolicyDependencyNode,
    target: PolicyDependencyNode,
    evidence: tuple[EvidenceRef, ...],
) -> PolicyDependencyEdgeId:
    payload = {
        "kind": kind.value,
        "source": source.identity(),
        "target": target.identity(),
        "evidence": tuple(item.model_dump(mode="json") for item in evidence),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"policy-dependency:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def policy_dependency_edge(
    kind: PolicyDependencyKind,
    source: PolicyDependencyNode,
    target: PolicyDependencyNode,
    evidence: tuple[EvidenceRef, ...],
) -> PolicyDependencyEdge:
    return PolicyDependencyEdge(
        edge_id=policy_dependency_edge_id(kind, source, target, evidence),
        kind=kind,
        source=source,
        target=target,
        evidence=evidence,
    )


def policy_relation_dependency_kind(kind: PolicyRuleRelationKind) -> PolicyDependencyKind:
    return PolicyDependencyKind(kind.value)


def policy_scope_node(scope: PolicyScope) -> PolicyDependencyNode:
    return PolicyDependencyNode(
        kind=PolicyDependencyNodeKind.SCOPE,
        object_id="federal" if scope.scope_id is None else scope.scope_id,
    )


def policy_rule_node(selection: PolicySelection) -> PolicyDependencyNode:
    return PolicyDependencyNode(
        kind=PolicyDependencyNodeKind.POLICY_RULE,
        object_id=selection.rule_id,
        revision=selection.revision,
        content_hash=selection.revision_hash,
    )


def domain_rule_node(reference: DomainRuleRef) -> PolicyDependencyNode:
    return PolicyDependencyNode(
        kind=PolicyDependencyNodeKind.DOMAIN_RULE,
        object_id=reference.canonical_rule_id,
        revision=reference.owner_revision,
        owner_module=reference.owner_module.value,
    )


def dependencies_for_policy_revision(
    revision: PolicyRuleRevision,
) -> tuple[PolicyDependencyEdge, ...]:
    source = PolicySelection(
        rule_id=revision.rule_id,
        revision=revision.revision,
        revision_hash=revision.content_hash,
        domain_rule=revision.domain_rule,
    )
    source_node = policy_rule_node(source)
    edges = [
        policy_dependency_edge(
            PolicyDependencyKind.APPLIES_TO,
            source_node,
            policy_scope_node(revision.scope),
            revision.evidence,
        ),
        policy_dependency_edge(
            PolicyDependencyKind.IMPLEMENTS,
            source_node,
            domain_rule_node(revision.domain_rule),
            revision.evidence,
        ),
    ]
    for relation in revision.relations:
        kind = policy_relation_dependency_kind(relation.kind)
        edges.append(
            policy_dependency_edge(
                kind,
                source_node,
                PolicyDependencyNode(
                    kind=PolicyDependencyNodeKind.POLICY_RULE,
                    object_id=relation.target_rule_id,
                    revision=relation.target_revision,
                    content_hash=relation.target_hash,
                ),
                (relation.evidence,),
            )
        )
    return tuple(sorted(edges, key=lambda item: (item.kind.value, item.edge_id)))


__all__ = [
    "PolicyDependencyEdge",
    "PolicyDependencyEdgeId",
    "PolicyDependencyKind",
    "PolicyDependencyNode",
    "PolicyDependencyNodeKind",
    "PolicyDependencyTraversal",
    "PolicyDependencyTraversalRequest",
    "dependencies_for_policy_revision",
    "domain_rule_node",
    "policy_dependency_edge",
    "policy_dependency_edge_id",
    "policy_relation_dependency_kind",
    "policy_rule_node",
    "policy_scope_node",
]
