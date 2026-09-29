from __future__ import annotations

from andromeda.modules.knowledge.contracts.public import EvidenceRef
from andromeda.modules.policy.contracts.dependencies import (
    PolicyDependencyKind,
    PolicyDependencyNode,
    PolicyDependencyNodeKind,
    PolicyDependencyTraversalRequest,
    policy_dependency_edge,
)
from andromeda.modules.policy.domain.dependencies import traverse_policy_dependencies


def _rule(rule_id: str, token: str) -> PolicyDependencyNode:
    return PolicyDependencyNode(
        kind=PolicyDependencyNodeKind.POLICY_RULE,
        object_id=rule_id,
        revision=1,
        content_hash=token * 64,
    )


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        source_id="source:official-rules",
        source_observation_id="source-observation:" + "1" * 32,
        snapshot_sha256="2" * 64,
        source_url="https://official.example/rules",
    )


def test_dependency_traversal_is_ordered_bounded_and_reports_cycles() -> None:
    a = _rule("policy-rule:a", "a")
    b = _rule("policy-rule:b", "b")
    c = _rule("policy-rule:c", "c")
    evidence = (_evidence(),)
    ab = policy_dependency_edge(PolicyDependencyKind.REQUIRES, a, b, evidence)
    ba = policy_dependency_edge(PolicyDependencyKind.REQUIRES, b, a, evidence)
    bc = policy_dependency_edge(PolicyDependencyKind.REQUIRES, b, c, evidence)

    result = traverse_policy_dependencies(
        PolicyDependencyTraversalRequest(root=a),
        (bc, ba, ab),
    )

    assert tuple(node.object_id for node in result.nodes) == (
        "policy-rule:a",
        "policy-rule:b",
        "policy-rule:c",
    )
    assert result.cycles == (ba.edge_id,)
    assert result.edges == tuple(sorted((ab.edge_id, ba.edge_id, bc.edge_id)))
    assert result.maximum_depth == 2
    assert result.truncated is False


def test_dependency_traversal_marks_depth_and_node_caps() -> None:
    a = _rule("policy-rule:a", "a")
    b = _rule("policy-rule:b", "b")
    c = _rule("policy-rule:c", "c")
    d = _rule("policy-rule:d", "d")
    evidence = (_evidence(),)
    edges = (
        policy_dependency_edge(PolicyDependencyKind.REQUIRES, a, b, evidence),
        policy_dependency_edge(PolicyDependencyKind.REQUIRES, b, c, evidence),
        policy_dependency_edge(PolicyDependencyKind.REQUIRES, c, d, evidence),
    )

    result = traverse_policy_dependencies(
        PolicyDependencyTraversalRequest(root=a, max_depth=2),
        edges,
    )

    assert len(result.nodes) == 3
    assert result.maximum_depth == 2
    assert result.truncated is True
