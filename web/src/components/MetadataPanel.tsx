import { StatusBadge } from "./StatusBadge";
import type { MetadataEntry } from "../lib/types";

// Renders a metadata entry incl. the custom kv map (04). Editing wires into the
// metadata patch endpoints in Design (05) / Plan (06); read view lives here.
export function MetadataPanel({ entry }: { entry: MetadataEntry }) {
  const custom = Object.entries(entry.custom ?? {});
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="text-xs uppercase tracking-wide text-slate-400">Name</div>
        <div className="font-medium text-slate-900">{entry.name}</div>
      </div>
      <div>
        <div className="text-xs uppercase tracking-wide text-slate-400">Type</div>
        <div className="text-slate-700">{entry.type}</div>
      </div>
      {entry.status && (
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Status</div>
          <StatusBadge status={entry.status} />
        </div>
      )}
      {entry.description && (
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Description</div>
          <div className="text-slate-700">{entry.description}</div>
        </div>
      )}
      {entry.taskGroup && (
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Group</div>
          <div className="text-slate-700">{entry.taskGroup}</div>
        </div>
      )}
      {custom.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Custom</div>
          <dl className="mt-1 space-y-0.5">
            {custom.map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <dt className="text-slate-500">{k}:</dt>
                <dd className="text-slate-700">{String(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}
