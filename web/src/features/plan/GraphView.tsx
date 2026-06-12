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
import { GroupNode, LitContext, StatusNode } from "./nodes";
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

  // Hovered task + its dependency tree. Kept out of the nodes array so hovering
  // doesn't churn React Flow's node bookkeeping (dimming flows via LitContext).
  const hl = useMemo(() => {
    if (!hover) return null;
    const anc = ancestors(hover, graph.edges);
    const desc = descendants(hover, graph.edges);
    return { anc, desc, lit: new Set<string>([hover, ...anc, ...desc]) };
  }, [hover, graph.edges]);

  // Nodes only depend on selection — never on hover — so the array reference is
  // stable while the mouse moves over the graph.
  const nodes: Node[] = useMemo(
    () =>
      base.nodes.map((n) =>
        n.type === "group" ? n : { ...n, selected: n.id === selectedTaskId },
      ),
    [base.nodes, selectedTaskId],
  );

  const edges: Edge[] = useMemo(() => {
    const inSet = (id: string, s: Set<string> | null) => !!s && (s.has(id) || id === hover);
    return base.edges.map((e) => {
      let color = EDGE_BASE;
      let dim = false;
      if (hl) {
        const isAnc = inSet(e.source, hl.anc) && inSet(e.target, hl.anc);
        const isDesc = inSet(e.source, hl.desc) && inSet(e.target, hl.desc);
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
  }, [base.edges, hl, hover]);

  return (
    <LitContext.Provider value={hl?.lit ?? null}>
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
    </LitContext.Provider>
  );
}
