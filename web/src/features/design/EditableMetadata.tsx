import { useState } from "react";
import { usePatchMetadata, useSetTaskStatus } from "../../lib/queries";
import { STATUS_META } from "../../lib/status";
import type { MetadataEntry, TaskStatus } from "../../lib/types";
import { collectionForType } from "./util";

const EDITABLE_STATUSES: TaskStatus[] = [
  "pending",
  "in_progress",
  "in_review",
  "blocked",
  "done",
];

// The Design sidebar's metadata section: read + inline edit (description, group,
// status for tasks, custom kv). Saves via the metadata/status endpoints.
export function EditableMetadata({ entry }: { entry: MetadataEntry }) {
  const collection = collectionForType(entry.type);
  const patch = usePatchMetadata();
  const setStatus = useSetTaskStatus();
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");

  const savePatch = (p: Record<string, unknown>) =>
    patch.mutate({ collection, id: entry.id, patch: p });

  const custom = Object.entries(entry.custom ?? {});

  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="text-xs uppercase tracking-wide text-slate-400">{entry.type}</div>
        <div className="font-medium text-slate-900">{entry.name}</div>
      </div>

      {entry.type === "task" && (
        <div>
          <label className="text-xs uppercase tracking-wide text-slate-400">Status</label>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
            value={entry.status ?? "pending"}
            onChange={(e) =>
              setStatus.mutate({ id: entry.id, status: e.target.value as TaskStatus })
            }
          >
            {EDITABLE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_META[s].label}
              </option>
            ))}
          </select>
        </div>
      )}

      <div>
        <label className="text-xs uppercase tracking-wide text-slate-400">Description</label>
        <textarea
          className="mt-1 w-full resize-none rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
          defaultValue={entry.description}
          rows={2}
          onBlur={(e) => {
            if (e.target.value !== entry.description)
              savePatch({ description: e.target.value });
          }}
        />
      </div>

      <div>
        <label className="text-xs uppercase tracking-wide text-slate-400">Group</label>
        <input
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
          defaultValue={entry.taskGroup ?? ""}
          onBlur={(e) => {
            if (e.target.value !== (entry.taskGroup ?? ""))
              savePatch({ taskGroup: e.target.value || null });
          }}
        />
      </div>

      {entry.dependsOn.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Depends on</div>
          <div className="text-slate-600">{entry.dependsOn.length} task(s)</div>
        </div>
      )}

      {entry.executionId && (
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Execution</div>
          <code className="text-xs text-slate-600">{entry.executionId}</code>
        </div>
      )}

      <div>
        <div className="text-xs uppercase tracking-wide text-slate-400">Custom fields</div>
        <dl className="mt-1 space-y-1">
          {custom.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <dt className="text-slate-500">{k}:</dt>
              <dd className="flex-1 text-slate-700">{String(v)}</dd>
              <button
                className="text-xs text-slate-400 hover:text-red-600"
                onClick={() => {
                  const next = { ...entry.custom };
                  delete next[k];
                  savePatch({ custom: next });
                }}
              >
                ✕
              </button>
            </div>
          ))}
        </dl>
        <div className="mt-1 flex gap-1">
          <input
            className="w-20 rounded border border-slate-300 px-1.5 py-1 text-xs"
            placeholder="key"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
          />
          <input
            className="flex-1 rounded border border-slate-300 px-1.5 py-1 text-xs"
            placeholder="value"
            value={newVal}
            onChange={(e) => setNewVal(e.target.value)}
          />
          <button
            className="rounded bg-slate-100 px-2 text-xs hover:bg-slate-200 disabled:opacity-40"
            disabled={!newKey.trim()}
            onClick={() => {
              savePatch({ custom: { ...entry.custom, [newKey.trim()]: newVal } });
              setNewKey("");
              setNewVal("");
            }}
          >
            Add
          </button>
        </div>
      </div>
    </div>
  );
}
