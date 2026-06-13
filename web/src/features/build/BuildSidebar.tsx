import { useState } from "react";
import { useTasks } from "../../lib/queries";
import { STATUS_META } from "../../lib/status";
import { Spinner } from "../../components/Spinner";
import type { MetadataEntry, TaskStatus } from "../../lib/types";

// Build sidebar (08): tasks grouped into collapsible status sections. "Active"
// (in_progress + in_review) is open by default; the rest start collapsed.
type Group = { key: string; label: string; statuses: TaskStatus[]; defaultOpen: boolean };

const GROUPS: Group[] = [
  { key: "active", label: "In progress / review", statuses: ["in_progress", "in_review"], defaultOpen: true },
  { key: "blocked", label: "Blocked", statuses: ["blocked"], defaultOpen: false },
  { key: "pending", label: "Pending", statuses: ["pending"], defaultOpen: false },
  { key: "done", label: "Done", statuses: ["done"], defaultOpen: false },
];

export function BuildSidebar({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { data: tasks } = useTasks();
  const visible = (tasks ?? []).filter((t) => t.status && t.status !== "removed");

  return (
    <aside className="flex h-full w-72 flex-col overflow-auto border-r border-slate-200 bg-slate-50">
      <div className="border-b border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700">
        Tasks
      </div>
      {visible.length === 0 ? (
        <p className="p-3 text-sm text-slate-400">No tasks yet. Create them in Plan.</p>
      ) : (
        GROUPS.map((g) => {
          const items = visible.filter((t) => g.statuses.includes(t.status as TaskStatus));
          return (
            <Section key={g.key} group={g} count={items.length}>
              {items.map((t) => (
                <Row
                  key={t.id}
                  task={t}
                  selected={t.id === selectedId}
                  onSelect={() => onSelect(t.id)}
                />
              ))}
            </Section>
          );
        })
      )}
    </aside>
  );
}

function Section({
  group,
  count,
  children,
}: {
  group: Group;
  count: number;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(group.defaultOpen);
  return (
    <div className="border-b border-slate-200">
      <button
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 hover:bg-slate-100"
        onClick={() => setOpen((o) => !o)}
      >
        <span>
          {open ? "▾" : "▸"} {group.label}
        </span>
        <span className="text-slate-400">{count}</span>
      </button>
      {open && count > 0 && <div className="pb-1">{children}</div>}
      {open && count === 0 && (
        <p className="px-3 pb-2 text-xs text-slate-400">None</p>
      )}
    </div>
  );
}

function Row({
  task,
  selected,
  onSelect,
}: {
  task: MetadataEntry;
  selected: boolean;
  onSelect: () => void;
}) {
  const meta = task.status ? STATUS_META[task.status] : null;
  const errored = !!task.executionError;
  return (
    <button
      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm ${
        selected
          ? "bg-blue-100 text-blue-800"
          : errored
            ? "text-red-700 hover:bg-red-50"
            : "text-slate-700 hover:bg-slate-100"
      }`}
      onClick={onSelect}
      title={errored ? "This execution hit an error — open it to retry" : undefined}
    >
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          errored ? "bg-red-500" : meta ? meta.dot : "bg-transparent"
        }`}
      />
      <span className={`min-w-0 flex-1 truncate ${errored ? "font-medium" : ""}`}>
        {task.name}
      </span>
      {errored && <span className="shrink-0 text-xs text-red-500">⚠</span>}
      {task.status === "in_progress" && task.executionId && !errored && (
        <Spinner className="text-blue-500" />
      )}
    </button>
  );
}
