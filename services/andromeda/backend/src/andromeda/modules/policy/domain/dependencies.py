"""Bounded deterministic traversal over typed policy dependency edges."""

from __future__ import annotations

from collections import defaultdict

from andromeda.modules.policy.contracts.dependencies import (
    PolicyDependencyEdge,
    PolicyDependencyNode,
    PolicyDependencyTraversal,
    PolicyDependencyTraversalRequest,
)


def traverse_policy_dependencies(
    request: PolicyDependencyTraversalRequest,
    edges: tuple[PolicyDependencyEdge, ...],
) -> PolicyDependencyTraversal:
    if len(edges) > 10000:
        raise ValueError("Policy dependency input exceeds the 10000-edge traversal budget")
    adjacency: dict[tuple[str, str, int | None, str | None, str | None], list[PolicyDependencyEdge]] = (
        defaultdict(list)
    )
    for edge in edges:
        adjacency[edge.source.identity()].append(edge)
    for outgoing in adjacency.values():
        outgoing.sort(key=lambda edge: edge.edge_id)

    root_key = request.root.identity()
    nodes: dict[tuple[str, str, int | None, str | None, str | None], PolicyDependencyNode] = {
        root_key: request.root
    }
    depths = {root_key: 0}
    paths: dict[
        tuple[str, str, int | None, str | None, str | None],
        frozenset[tuple[str, str, int | None, str | None, str | None]],
    ] = {root_key: frozenset({root_key})}
    pending = [request.root]
    traversed_edges: dict[str, PolicyDependencyEdge] = {}
    cycles: set[str] = set()
    truncated = False

    while pending:
        current = pending.pop(0)
        current_key = current.identity()
        depth = depths[current_key]
        outgoing = adjacency.get(current_key, [])
        if depth >= request.max_depth:
            if outgoing:
                truncated = True
            continue
        for edge in outgoing:
            traversed_edges[edge.edge_id] = edge
            target_key = edge.target.identity()
            if target_key in paths[current_key]:
                cycles.add(edge.edge_id)
                continue
            if target_key in nodes:
                continue
            if len(nodes) >= request.max_nodes:
                truncated = True
                continue
            nodes[target_key] = edge.target
            depths[target_key] = depth + 1
            paths[target_key] = paths[current_key] | {target_key}
            pending.append(edge.target)

    ordered_nodes = tuple(nodes[key] for key in sorted(nodes, key=lambda key: (depths[key], key)))
    return PolicyDependencyTraversal(
        root=request.root,
        nodes=ordered_nodes,
        edges=tuple(sorted(traversed_edges)),
        cycles=tuple(sorted(cycles)),
        truncated=truncated,
        maximum_depth=max(depths.values(), default=0),
    )


__all__ = ["traverse_policy_dependencies"]
