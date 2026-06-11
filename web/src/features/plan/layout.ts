import dagre from "dagre";
import type { Node, Edge } from "@xyflow/react";
import type { DependencyGraph, GraphNode, TaskStatus } from "../../lib/types";

export const NODE_W = 180;
export const NODE_H = 52;
const GROUP_PAD = 28;
const GROUP_GAP = 64;
const GROUP_HEADER = 28;

const UNGROUPED = "Ungrouped";

export interface StatusNodeData extends Record<string, unknown> {
  name: string;
  status?: TaskStatus | null;
}

/**
 * Lay the dependency graph out as React Flow nodes/edges. Strategy (per 06): run
 * dagre on each task-group's subgraph, then stack the group blocks vertically so
 * clusters never overlap; group containers are background nodes sized to their
 * block. Cross-group edges still render between absolute positions.
 */
export function layoutGraph(graph: DependencyGraph): { nodes: Node[]; edges: Edge[] } {
  const byGroup = new Map<string, GraphNode[]>();
  for (const n of graph.nodes) {
    const g = n.taskGroup || UNGROUPED;
    (byGroup.get(g) ?? byGroup.set(g, []).get(g)!).push(n);
  }
  const idToGroup = new Map(graph.nodes.map((n) => [n.id, n.taskGroup || UNGROUPED]));

  const nodes: Node[] = [];
  let offsetY = 0;

  // Stable group order: named groups first (alpha), Ungrouped last.
  const groupNames = [...byGroup.keys()].sort((a, b) =>
    a === UNGROUPED ? 1 : b === UNGROUPED ? -1 : a.localeCompare(b),
  );

  for (const group of groupNames) {
    const groupNodes = byGroup.get(group)!;
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "LR", nodesep: 24, ranksep: 70, marginx: 0, marginy: 0 });
    g.setDefaultEdgeLabel(() => ({}));
    for (const n of groupNodes) g.setNode(n.id, { width: NODE_W, height: NODE_H });
    for (const e of graph.edges) {
      if (idToGroup.get(e.source) === group && idToGroup.get(e.target) === group) {
        g.setEdge(e.source, e.target);
      }
    }
    dagre.layout(g);

    let maxX = 0;
    let maxY = 0;
    const placed: { id: string; x: number; y: number }[] = [];
    for (const n of groupNodes) {
      const p = g.node(n.id);
      // dagre gives center coords; convert to top-left.
      const x = (p?.x ?? NODE_W / 2) - NODE_W / 2;
      const y = (p?.y ?? NODE_H / 2) - NODE_H / 2;
      placed.push({ id: n.id, x, y });
      maxX = Math.max(maxX, x + NODE_W);
      maxY = Math.max(maxY, y + NODE_H);
    }

    const blockW = maxX + GROUP_PAD * 2;
    const blockH = maxY + GROUP_PAD * 2 + GROUP_HEADER;

    // Group container (background) node.
    nodes.push({
      id: `group:${group}`,
      type: "group",
      position: { x: 0, y: offsetY },
      data: { label: group },
      draggable: false,
      selectable: false,
      style: { width: blockW, height: blockH },
      zIndex: 0,
    });

    // Task nodes, absolute-positioned inside the block.
    for (const pl of placed) {
      const gn = groupNodes.find((n) => n.id === pl.id)!;
      nodes.push({
        id: gn.id,
        type: "status",
        position: {
          x: GROUP_PAD + pl.x,
          y: offsetY + GROUP_HEADER + GROUP_PAD + pl.y,
        },
        data: { name: gn.name, status: gn.status } as StatusNodeData,
        zIndex: 1,
      });
    }

    offsetY += blockH + GROUP_GAP;
  }

  const edges: Edge[] = graph.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
  }));

  return { nodes, edges };
}

/** Tasks `id` depends on (transitive), following edges backward (target→source). */
export function ancestors(id: string, edges: { source: string; target: string }[]): Set<string> {
  const out = new Set<string>();
  const stack = [id];
  while (stack.length) {
    const cur = stack.pop()!;
    for (const e of edges) {
      if (e.target === cur && !out.has(e.source)) {
        out.add(e.source);
        stack.push(e.source);
      }
    }
  }
  return out;
}

/** Tasks that depend on `id` (transitive), following edges forward (source→target). */
export function descendants(id: string, edges: { source: string; target: string }[]): Set<string> {
  const out = new Set<string>();
  const stack = [id];
  while (stack.length) {
    const cur = stack.pop()!;
    for (const e of edges) {
      if (e.source === cur && !out.has(e.target)) {
        out.add(e.target);
        stack.push(e.target);
      }
    }
  }
  return out;
}
