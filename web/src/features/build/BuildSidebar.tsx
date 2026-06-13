import { useState } from "react";
import { useStartExecution, useTasks } from "../../lib/queries";
import { STATUS_META } from "../../lib/status";
import { Spinner } from "../../components/Spinner";
import type { MetadataEntry } from "../../lib/types";

// Build sidebar: only tasks relevant to building are shown, in dependency order —
//   1. Executing  — tasks with an active (not-yet-in-review) execution
//   2. In review  — tasks whose build finished and await review
//   3. Up next    — unstarted tasks whose dependencies are all done (ready to build)
export function BuildSidebar({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { data: tasks } = useTasks();
  const start = useStartExecution();
  const all = (tasks ?? []).filter((t) => t.status !== "removed");
  const byId = new Map(all.map((t) => [t.id, t]));

  const executing = all.filter(
    (t) => t.executionId && t.status !== "in_review" && t.status !== "done",
  );
  const inReview = all.filter((t) => t.status === "in_review");
  // "Up next": not started yet, and every dependency is already done.
  const upNext = all.filter(
    (t) =>
      !t.executionId &&
      t.status === "pending" &&
      (t.dependsOn ?? []).every((d) => byId.get(d)?.status === "done"),
  );

  const startAll = () => {
    upNext.forEach((t) => start.mutate({ taskId: t.id }));
  };

  const empty = !executing.length && !inReview.length && !upNext.length;

  return (
    <aside className="flex h-full w-72 flex-col overflow-auto border-r border-slate-200 bg-slate-50">
      <div className="border-b border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700">
        Tasks
      </div>
      {empty ? (
        <p className="p-3 text-sm text-slate-400">
          No tasks to build yet. Create them in Plan, or finish a task's dependencies.
        </p>
      ) : (
        <>
          <Section label="Executing" count={executing.length}>
            {executing.map((t) => (
              <Row key={t.id} task={t} selected={t.id === selectedId} onSelect={() => onSelect(t.id)} />
            ))}
          </Section>
          <Section label="In review" count={inReview.length}>
            {inReview.map((t) => (
              <Row key={t.id} task={t} selected={t.id === selectedId} onSelect={() => onSelect(t.id)} />
            ))}
          </Section>
          <Section
            label="Up next"
            count={upNext.length}
            action={
              upNext.length > 0 ? (
                <button
                  className="rounded bg-blue-600 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  onClick={(e) => {
                    e.stopPropagation();
                    startAll();
                  }}
                  disabled={start.isPending}
                  title="Start executions for all up-next tasks"
                >
                  {start.isPending ? "Starting…" : "Start all"}
                </button>
              ) : undefined
            }
          >
            {upNext.map((t) => (
              <Row key={t.id} task={t} selected={t.id === selectedId} onSelect={() => onSelect(t.id)} />
            ))}
          </Section>
        </>
      )}
    </aside>
  );
}

function Section({
  label,
  count,
  action,
  children,
}: {
  label: string;
  count: number;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="border-b border-slate-200">
      <div className="flex w-full items-center gap-2 px-3 py-2">
        <button
          className="flex flex-1 items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700"
          onClick={() => setOpen((o) => !o)}
        >
          <span>
            {open ? "▾" : "▸"} {label}
          </span>
          <span className="text-slate-400">{count}</span>
        </button>
        {action}
      </div>
      {open && count > 0 && <div className="pb-1">{children}</div>}
      {open && count === 0 && <p className="px-3 pb-2 text-xs text-slate-400">None</p>}
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
  const blocked = !errored && !!task.executionBlocked;
  return (
    <button
      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm ${
        selected
          ? "bg-blue-100 text-blue-800"
          : errored
            ? "text-red-700 hover:bg-red-50"
            : blocked
              ? "text-amber-700 hover:bg-amber-50"
              : "text-slate-700 hover:bg-slate-100"
      }`}
      onClick={onSelect}
      title={
        errored
          ? "This execution hit an error — open it to retry"
          : blocked
            ? "Claude hit a blocker — open it to respond"
            : undefined
      }
    >
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          errored ? "bg-red-500" : blocked ? "bg-amber-500" : meta ? meta.dot : "bg-transparent"
        }`}
      />
      <span className={`min-w-0 flex-1 truncate ${errored || blocked ? "font-medium" : ""}`}>
        {task.name}
      </span>
      {errored && <span className="shrink-0 text-xs text-red-500">⚠</span>}
      {blocked && <span className="shrink-0 text-xs text-amber-500">⚠</span>}
      {task.status === "in_progress" && task.executionId && !errored && !blocked && (
        <Spinner className="text-blue-500" />
      )}
    </button>
  );
}
