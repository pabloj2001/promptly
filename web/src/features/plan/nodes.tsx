import { createContext, useContext } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { STATUS_META } from "../../lib/status";
import type { TaskStatus } from "../../lib/types";

// The currently "lit" set (hovered task + its dependency tree), or null when nothing
// is hovered. Delivered via context so hovering doesn't rebuild the nodes array — that
// churn made React Flow loop mouseenter/leave (cursor + opacity flicker).
export const LitContext = createContext<Set<string> | null>(null);

// A task node, colored by status. Dimming derives from the hovered dependency tree
// (LitContext); selection comes from the node prop.
export function StatusNode({ id, data, selected }: NodeProps) {
  const d = data as { name: string; status?: TaskStatus | null };
  const lit = useContext(LitContext);
  const dimmed = lit ? !lit.has(id) : false;
  const meta = d.status ? STATUS_META[d.status] : null;
  const surface = meta?.surface ?? "bg-white border-slate-300";
  const running = d.status === "in_progress";
  return (
    <div className="relative" style={{ width: 180 }}>
      {running && (
        <span className="pointer-events-none absolute -inset-0.5 animate-pulse rounded-lg ring-2 ring-blue-400" />
      )}
      <div
        className={`cursor-pointer rounded-md border px-3 py-2 shadow-sm transition-opacity ${surface} ${
          selected ? "!border-blue-500 ring-2 ring-blue-300" : ""
        } ${dimmed ? "opacity-30" : "opacity-100"}`}
      >
        <Handle type="target" position={Position.Left} className="!bg-slate-400" />
        <div className="flex items-center gap-2">
          {meta && <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />}
          <span className="truncate text-sm font-medium text-slate-800">{d.name}</span>
        </div>
        {meta && <div className="mt-0.5 text-xs text-slate-400">{meta.label}</div>}
        <Handle type="source" position={Position.Right} className="!bg-slate-400" />
      </div>
    </div>
  );
}

// Background container for a task group.
export function GroupNode({ data }: NodeProps) {
  const d = data as { label: string };
  return (
    <div className="h-full w-full rounded-lg border border-dashed border-slate-300 bg-slate-50/60">
      <div className="px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {d.label}
      </div>
    </div>
  );
}
