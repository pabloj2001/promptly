"""Dependency graph helpers for the Plan tab + cycle detection on writes.

An edge points from a dependency to the dependent task: if task B ``dependsOn``
A, the edge is A -> B ("A must finish before B"). ``removed`` tasks are excluded
unless explicitly requested.
"""

from __future__ import annotations

from ..models import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    MetadataEntry,
    TaskStatus,
)


def build_graph(
    entries: dict[str, MetadataEntry], include_removed: bool = False
) -> DependencyGraph:
    visible = {
        eid: e
        for eid, e in entries.items()
        if include_removed or e.status != TaskStatus.removed.value
    }
    nodes = [
        GraphNode(
            id=e.id, name=e.name, status=e.status, task_group=e.task_group
        )
        for e in visible.values()
    ]
    edges: list[GraphEdge] = []
    for e in visible.values():
        for dep in e.depends_on:
            if dep in visible:  # don't render edges to hidden/removed nodes
                edges.append(GraphEdge(source=dep, target=e.id))
    return DependencyGraph(nodes=nodes, edges=edges)


def would_create_cycle(
    entries: dict[str, MetadataEntry], task_id: str, new_depends_on: list[str]
) -> bool:
    """True if setting ``task_id.dependsOn = new_depends_on`` introduces a cycle.

    We walk the dependency direction (follow ``dependsOn``): if any proposed
    dependency can already reach ``task_id`` through existing edges, adding it
    closes a loop.
    """
    adj: dict[str, list[str]] = {eid: list(e.depends_on) for eid, e in entries.items()}
    adj[task_id] = list(new_depends_on)

    def reaches(start: str, target: str) -> bool:
        seen: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur == target:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adj.get(cur, []))
        return False

    # A self-dependency is always a cycle.
    if task_id in new_depends_on:
        return True
    # If any dependency depends (transitively) on task_id, we'd loop.
    return any(reaches(dep, task_id) for dep in new_depends_on)
