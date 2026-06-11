import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { useTasks } from "../../lib/queries";
import { useUiStore } from "../../store";
import { STATUS_META } from "../../lib/status";
import type { MetadataEntry, TaskStatus } from "../../lib/types";

const COLUMNS: TaskStatus[] = ["pending", "in_progress", "blocked", "in_review", "done"];

export function BoardView({ onSelect }: { onSelect: (id: string) => void }) {
  const { data: tasks } = useTasks();
  const project = useUiStore((s) => s.activeProject);
  const selectedTaskId = useUiStore((s) => s.selectedTaskId);
  const qc = useQueryClient();
  const [dragId, setDragId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const visible = (tasks ?? []).filter((t) => t.status !== "removed");
  const byStatus = (s: TaskStatus) => visible.filter((t) => t.status === s);

  const move = async (id: string, status: TaskStatus) => {
    const task = visible.find((t) => t.id === id);
    if (!task || task.status === status) return;
    setError(null);
    const key = ["tasks", project];
    await qc.cancelQueries({ queryKey: key });
    const prev = qc.getQueryData<MetadataEntry[]>(key);
    // optimistic
    qc.setQueryData<MetadataEntry[]>(key, (cur) =>
      cur?.map((t) => (t.id === id ? { ...t, status } : t)),
    );
    try {
      await api.setTaskStatus(id, status);
      qc.invalidateQueries({ queryKey: ["taskGraph", project] });
    } catch (e) {
      qc.setQueryData(key, prev); // revert
      setError(e instanceof Error ? e.message : "Could not change status");
    } finally {
      qc.invalidateQueries({ queryKey: key });
    }
  };

  return (
    <div className="flex h-full flex-col">
      {error && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-1.5 text-sm text-red-700">
          {error}
        </div>
      )}
      <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto p-4">
        {COLUMNS.map((col) => (
          <div
            key={col}
            className="flex w-64 shrink-0 flex-col rounded-lg bg-slate-100"
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => dragId && move(dragId, col)}
          >
            <div className="flex items-center gap-2 px-3 py-2 text-sm font-semibold text-slate-600">
              <span className={`h-2 w-2 rounded-full ${STATUS_META[col].dot}`} />
              {STATUS_META[col].label}
              <span className="text-slate-400">{byStatus(col).length}</span>
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-auto px-2 pb-2">
              {byStatus(col).map((t) => (
                <button
                  key={t.id}
                  draggable
                  onDragStart={() => setDragId(t.id)}
                  onDragEnd={() => setDragId(null)}
                  onClick={() => onSelect(t.id)}
                  className={`block w-full cursor-grab rounded-md border bg-white px-3 py-2 text-left shadow-sm active:cursor-grabbing ${
                    selectedTaskId === t.id ? "border-blue-500 ring-1 ring-blue-300" : "border-slate-200"
                  }`}
                >
                  <div className="truncate text-sm font-medium text-slate-800">{t.name}</div>
                  {t.taskGroup && (
                    <div className="mt-1 inline-block rounded bg-slate-100 px-1.5 text-xs text-slate-500">
                      {t.taskGroup}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
