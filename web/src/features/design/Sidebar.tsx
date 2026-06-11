import { useState } from "react";
import { PromptDialog, type PromptResult } from "../../components/PromptDialog";
import { StatusBadge } from "../../components/StatusBadge";
import { useCreateDoc, useCreateTask, useDocs, useTasks } from "../../lib/queries";
import type { MetadataEntry } from "../../lib/types";
import { EditableMetadata } from "./EditableMetadata";

type NewKind = "doc" | "task" | null;

export function Sidebar({
  selected,
  selectedId,
  onSelect,
}: {
  selected: MetadataEntry | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { data: docs } = useDocs();
  const { data: tasks } = useTasks();
  const [showRemoved, setShowRemoved] = useState(false);
  const [newKind, setNewKind] = useState<NewKind>(null);
  const [error, setError] = useState<string | null>(null);
  const createDoc = useCreateDoc();
  const createTask = useCreateTask();

  const spec = docs?.find((d) => d.type === "project_spec") ?? null;
  const supplemental = (docs ?? []).filter((d) => d.type === "doc");
  const visibleTasks = (tasks ?? []).filter(
    (t) => showRemoved || t.status !== "removed",
  );

  const submitNew = async (r: PromptResult) => {
    setError(null);
    try {
      const entry =
        newKind === "task"
          ? await createTask.mutateAsync({
              prompt: r.prompt,
              name: r.name,
              dependsOn: r.dependsOn,
            })
          : await createDoc.mutateAsync({
              prompt: r.prompt,
              type: "doc",
              name: r.name,
            });
      setNewKind(null);
      onSelect(entry.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    }
  };

  const Row = ({ entry }: { entry: MetadataEntry }) => (
    <button
      className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-sm ${
        selectedId === entry.id
          ? "bg-blue-100 text-blue-800"
          : "text-slate-700 hover:bg-slate-100"
      }`}
      onClick={() => onSelect(entry.id)}
    >
      <span className="truncate">{entry.name}</span>
      {entry.status && <StatusBadge status={entry.status} />}
    </button>
  );

  return (
    <aside className="flex h-full w-72 flex-col border-r border-slate-200 bg-slate-50">
      {selected && (
        <div className="border-b border-slate-200 p-3">
          <EditableMetadata entry={selected} />
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {spec && (
          <div className="mb-3">
            <Row entry={spec} />
          </div>
        )}

        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          docs/
        </div>
        <div className="mb-3 space-y-0.5">
          {supplemental.length === 0 && (
            <div className="px-2 text-xs text-slate-400">No docs yet</div>
          )}
          {supplemental.map((d) => (
            <Row key={d.id} entry={d} />
          ))}
        </div>

        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          tasks/
        </div>
        <div className="space-y-0.5">
          {visibleTasks.length === 0 && (
            <div className="px-2 text-xs text-slate-400">No tasks yet</div>
          )}
          {visibleTasks.map((t) => (
            <Row key={t.id} entry={t} />
          ))}
        </div>

        <label className="mt-3 flex items-center gap-1.5 px-2 text-xs text-slate-500">
          <input
            type="checkbox"
            checked={showRemoved}
            onChange={(e) => setShowRemoved(e.target.checked)}
          />
          Show removed
        </label>
      </div>

      <div className="flex gap-2 border-t border-slate-200 p-3">
        <button
          className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
          onClick={() => setNewKind("doc")}
        >
          + Doc
        </button>
        <button
          className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
          onClick={() => setNewKind("task")}
        >
          + Task
        </button>
      </div>

      <PromptDialog
        open={newKind !== null}
        onOpenChange={(o) => !o && setNewKind(null)}
        title={newKind === "task" ? "New task spec" : "New document"}
        description="Describe what you want; the AI will write it."
        submitLabel="Generate"
        busy={createDoc.isPending || createTask.isPending}
        error={error}
        dependencyOptions={newKind === "task" ? visibleTasks : undefined}
        onSubmit={submitNew}
      />
    </aside>
  );
}
