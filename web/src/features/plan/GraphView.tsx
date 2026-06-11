import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { DependencyGraph } from "../../lib/types";
import { useUiStore } from "../../store";
import { GroupNode, StatusNode } from "./nodes";
import { ancestors, descendants, layoutGraph } from "./layout";

const nodeTypes = { status: StatusNode, group: GroupNode };

const EDGE_DIM = "#e2e8f0";
const EDGE_BASE = "#94a3b8";
const EDGE_ANCESTOR = "#334155"; // darker — toward dependencies
const EDGE_DESCENDANT = "#60a5fa"; // lighter — toward dependents

export function GraphView({
  graph,
  onSelect,
}: {
  graph: DependencyGraph;
  onSelect: (id: string) => void;
}) {
  const selectedTaskId = useUiStore((s) => s.selectedTaskId);
  const [hover, setHover] = useState<string | null>(null);
  const base = useMemo(() => layoutGraph(graph), [graph]);

  const { nodes, edges } = useMemo(() => {
    const anc = hover ? ancestors(hover, graph.edges) : null;
    const desc = hover ? descendants(hover, graph.edges) : null;
    const lit = hover ? new Set<string>([hover, ...anc!, ...desc!]) : null;

    const nodes: Node[] = base.nodes.map((n) => {
      if (n.type === "group") return n;
      const dimmed = lit ? !lit.has(n.id) : false;
      return {
        ...n,
        selected: n.id === selectedTaskId,
        data: { ...n.data, dimmed },
      };
    });

    const inSet = (id: string, s: Set<string> | null, h: string | null) =>
      !!s && (s.has(id) || id === h);

    const edges: Edge[] = base.edges.map((e) => {
      let color = EDGE_BASE;
      let dim = false;
      if (hover) {
        const isAnc = inSet(e.source, anc, hover) && inSet(e.target, anc, hover);
        const isDesc = inSet(e.source, desc, hover) && inSet(e.target, desc, hover);
        if (isAnc) color = EDGE_ANCESTOR;
        else if (isDesc) color = EDGE_DESCENDANT;
        else {
          color = EDGE_DIM;
          dim = true;
        }
      }
      return {
        ...e,
        style: { stroke: color, strokeWidth: dim ? 1 : 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color },
      };
    });
    return { nodes, edges };
  }, [base, hover, selectedTaskId, graph.edges]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      nodesDraggable={false}
      fitView
      minZoom={0.2}
      onNodeClick={(_e, n) => n.type !== "group" && onSelect(n.id)}
      onNodeMouseEnter={(_e, n) => n.type !== "group" && setHover(n.id)}
      onNodeMouseLeave={() => setHover(null)}
      proOptions={{ hideAttribution: true }}
    >
      <Background />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
