import { Handle, Position, type NodeProps } from "@xyflow/react";
import { STATUS_META } from "../../lib/status";
import type { TaskStatus } from "../../lib/types";

// A task node, colored by status. Dimming/selection driven via `data` flags set by
// the graph on hover/selection.
export function StatusNode({ data, selected }: NodeProps) {
  const d = data as { name: string; status?: TaskStatus | null; dimmed?: boolean };
  const meta = d.status ? STATUS_META[d.status] : null;
  return (
    <div
      className={`rounded-md border bg-white px-3 py-2 shadow-sm transition-opacity ${
        selected ? "border-blue-500 ring-2 ring-blue-300" : "border-slate-300"
      } ${d.dimmed ? "opacity-30" : "opacity-100"}`}
      style={{ width: 180 }}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-400" />
      <div className="flex items-center gap-2">
        {meta && <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />}
        <span className="truncate text-sm font-medium text-slate-800">{d.name}</span>
      </div>
      {meta && <div className="mt-0.5 text-xs text-slate-400">{meta.label}</div>}
      <Handle type="source" position={Position.Right} className="!bg-slate-400" />
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
