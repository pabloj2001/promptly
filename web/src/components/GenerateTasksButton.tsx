import { useState } from "react";
import { Spinner } from "./Spinner";
import { useDocs, useGenerateTasksFromSpec } from "../lib/queries";

// Shown where a project has no tasks yet (Design sidebar + Plan blank slate, 05/06).
// Disabled until a project spec exists; on click the AI breaks the spec into tasks.
export function GenerateTasksButton({ className = "" }: { className?: string }) {
  const { data: docs } = useDocs();
  const generate = useGenerateTasksFromSpec();
  const [error, setError] = useState<string | null>(null);
  const hasSpec = (docs ?? []).some((d) => d.type === "project_spec");

  const run = async () => {
    setError(null);
    try {
      await generate.mutateAsync();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not generate tasks");
    }
  };

  return (
    <div className={className}>
      <button
        className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        onClick={run}
        disabled={generate.isPending || !hasSpec}
        title={hasSpec ? "Let AI break the spec into tasks" : "Create a project spec first"}
      >
        {generate.isPending && <Spinner />}
        {generate.isPending ? "Generating tasks…" : "Generate tasks from spec"}
      </button>
      {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
    </div>
  );
}
