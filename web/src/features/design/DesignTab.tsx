import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useDocs, useTasks } from "../../lib/queries";
import { useOperationsStream } from "../../lib/sse";
import { Spinner } from "../../components/Spinner";
import { EmptyState } from "./EmptyState";
import { Sidebar } from "./Sidebar";
import { DocView } from "./DocView";

export function DesignTab() {
  const { data: docs, isLoading: docsLoading } = useDocs();
  const { data: tasks, isLoading: tasksLoading } = useTasks();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("doc");

  // Live loading states for async AI operations (03/05).
  useOperationsStream();

  const allEntries = useMemo(() => [...(docs ?? []), ...(tasks ?? [])], [docs, tasks]);
  const spec = docs?.find((d) => d.type === "project_spec") ?? null;
  const selected = allEntries.find((e) => e.id === selectedId) ?? null;

  const select = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("doc", id);
    setParams(next, { replace: true });
  };

  // Default to the project spec once it exists and nothing is selected.
  useEffect(() => {
    if (!selectedId && spec) select(spec.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, spec?.id]);

  if (docsLoading || tasksLoading) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <Spinner />
      </div>
    );
  }

  // No project spec yet → focused empty state.
  if (!spec) {
    return <EmptyState onCreated={select} />;
  }

  return (
    <div className="flex h-full min-h-0">
      <Sidebar selected={selected} selectedId={selectedId} onSelect={select} />
      <div className="min-h-0 min-w-0 flex-1">
        {selected ? (
          <DocView key={selected.id} entry={selected} />
        ) : (
          <div className="flex h-full items-center justify-center text-slate-400">
            Select a document to view it.
          </div>
        )}
      </div>
    </div>
  );
}
