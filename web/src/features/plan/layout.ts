import dagre from "dagre";
import type { Node, Edge } from "@xyflow/react";
import type { DependencyGraph, GraphNode, TaskStatus } from "../../lib/types";

export const NODE_W = 180;
export const NODE_H = 52;
const GROUP_PAD = 28;
const GROUP_GAP_X = 56;
const GROUP_GAP_Y = 56;
const GROUP_HEADER = 28;

const UNGROUPED = "Ungrouped";

interface Block {
  group: string;
  placed: { id: string; x: number; y: number }[];
  blockW: number;
  blockH: number;
  x: number;
  y: number;
}

export interface StatusNodeData extends Record<string, unknown> {
  name: string;
  status?: TaskStatus | null;
}

/**
 * Lay the dependency graph out as React Flow nodes/edges. Strategy (per 06): run
 * dagre on each task-group's subgraph to get a compact block per group, then
 * shelf-pack those blocks into a grid (rows that wrap at a target width) so the
 * groups fill the space instead of stacking in one tall column. Group containers
 * are background nodes sized to their block; cross-group edges render between
 * absolute positions.
 */
export function layoutGraph(graph: DependencyGraph): { nodes: Node[]; edges: Edge[] } {
  const byGroup = new Map<string, GraphNode[]>();
  for (const n of graph.nodes) {
    const g = n.taskGroup || UNGROUPED;
    (byGroup.get(g) ?? byGroup.set(g, []).get(g)!).push(n);
  }
  const idToGroup = new Map(graph.nodes.map((n) => [n.id, n.taskGroup || UNGROUPED]));

  // Stable group order: named groups first (alpha), Ungrouped last.
  const groupNames = [...byGroup.keys()].sort((a, b) =>
    a === UNGROUPED ? 1 : b === UNGROUPED ? -1 : a.localeCompare(b),
  );

  // Pass 1: lay out each group internally (dagre) and measure its block.
  const blocks: Block[] = [];
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

    blocks.push({
      group,
      placed,
      blockW: maxX + GROUP_PAD * 2,
      blockH: maxY + GROUP_PAD * 2 + GROUP_HEADER,
      x: 0,
      y: 0,
    });
  }

  // Pass 2: shelf-pack blocks into a grid. Aim for a roughly landscape canvas:
  // target row width ≈ sqrt(totalArea · 1.6), but never narrower than the widest
  // block (so no block is forced onto its own overflowing row).
  const totalArea = blocks.reduce((a, b) => a + b.blockW * b.blockH, 0);
  const widest = blocks.reduce((m, b) => Math.max(m, b.blockW), 0);
  const targetWidth = Math.max(widest, Math.sqrt(totalArea * 1.6));

  let cursorX = 0;
  let cursorY = 0;
  let rowH = 0;
  for (const b of blocks) {
    if (cursorX > 0 && cursorX + b.blockW > targetWidth) {
      // Wrap to the next row.
      cursorX = 0;
      cursorY += rowH + GROUP_GAP_Y;
      rowH = 0;
    }
    b.x = cursorX;
    b.y = cursorY;
    cursorX += b.blockW + GROUP_GAP_X;
    rowH = Math.max(rowH, b.blockH);
  }

  // Pass 3: emit React Flow nodes at their packed positions.
  const nodes: Node[] = [];
  for (const b of blocks) {
    nodes.push({
      id: `group:${b.group}`,
      type: "group",
      position: { x: b.x, y: b.y },
      data: { label: b.group },
      draggable: false,
      selectable: false,
      style: { width: b.blockW, height: b.blockH },
      zIndex: 0,
    });

    for (const pl of b.placed) {
      const gn = byGroup.get(b.group)!.find((n) => n.id === pl.id)!;
      nodes.push({
        id: gn.id,
        type: "status",
        position: {
          x: b.x + GROUP_PAD + pl.x,
          y: b.y + GROUP_HEADER + GROUP_PAD + pl.y,
        },
        data: { name: gn.name, status: gn.status } as StatusNodeData,
        zIndex: 2,
      });
    }
  }

  // Render order: group background (0) < task edges (1) < task nodes (2), so
  // cross-group edges draw over the group containers but under the task cards.
  const edges: Edge[] = graph.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    zIndex: 1,
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
