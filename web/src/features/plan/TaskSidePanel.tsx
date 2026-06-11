import { useNavigate } from "react-router-dom";
import { useTasks } from "../../lib/queries";
import { EditableMetadata } from "../design/EditableMetadata";
import { StatusBadge } from "../../components/StatusBadge";
import { useUiStore } from "../../store";

// Shared inspector for both Plan views (06): editable metadata + before/after
// (direct deps/dependents) + Open-in-Design + Execute.
export function TaskSidePanel({
  taskId,
  onSelect,
  onClose,
}: {
  taskId: string;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const { data: tasks } = useTasks();
  const project = useUiStore((s) => s.activeProject);
  const navigate = useNavigate();

  const entry = tasks?.find((t) => t.id === taskId);
  if (!entry) return null;

  const before = (entry.dependsOn ?? [])
    .map((id) => tasks?.find((t) => t.id === id))
    .filter(Boolean);
  const after = (tasks ?? []).filter((t) => t.dependsOn?.includes(entry.id));

  const link = (id: string, name: string) => (
    <button
      key={id}
      className="block w-full truncate rounded px-2 py-1 text-left text-sm text-slate-700 hover:bg-slate-100"
      onClick={() => onSelect(id)}
    >
      {name}
    </button>
  );

  return (
    <aside className="flex h-full w-80 flex-col border-l border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <span className="text-sm font-semibold text-slate-700">Task</span>
        <button className="text-slate-400 hover:text-slate-700" onClick={onClose}>
          ✕
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-3">
        <EditableMetadata entry={entry} />

        <div>
          <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">
            Comes before (depends on)
          </div>
          {before.length === 0 ? (
            <p className="px-2 text-xs text-slate-400">None</p>
          ) : (
            before.map((t) => link(t!.id, t!.name))
          )}
        </div>

        <div>
          <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">
            Comes after (depended on by)
          </div>
          {after.length === 0 ? (
            <p className="px-2 text-xs text-slate-400">None</p>
          ) : (
            after.map((t) => (
              <div key={t.id} className="flex items-center gap-1 px-2">
                <StatusBadge status={t.status} />
                {link(t.id, t.name)}
              </div>
            ))
          )}
        </div>
      </div>

      <div className="flex gap-2 border-t border-slate-200 p-3">
        <button
          className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
          onClick={() =>
            navigate(`/p/${encodeURIComponent(project ?? "")}/design?doc=${entry.id}`)
          }
        >
          Open in Design
        </button>
        <button
          className="flex-1 rounded-md bg-blue-600 px-2 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          onClick={() =>
            navigate(`/p/${encodeURIComponent(project ?? "")}/build/${entry.id}`)
          }
        >
          Execute
        </button>
      </div>
    </aside>
  );
}
