import { useDiff } from "../../lib/queries";
import { parseUnifiedDiff, type DiffLine } from "../build/diff";

// Compact, read-only render of a doc-authoring execution's per-doc diff (the body
// snapshot before/after the run). No per-line comments — just the changes.
export function DocDiff({ executionId }: { executionId: string }) {
  const { data: diff, isLoading } = useDiff(executionId);

  if (isLoading) return <p className="text-xs text-slate-400">Loading changes…</p>;
  if (!diff || diff.files.length === 0)
    return <p className="text-xs text-slate-400">No changes.</p>;

  return (
    <div className="space-y-3">
      {diff.files.map((f) => (
        <div key={f.path} className="overflow-hidden rounded border border-slate-200">
          <div className="border-b border-slate-200 bg-slate-100 px-2 py-1 font-mono text-xs text-slate-600">
            {f.path}
          </div>
          <pre className="max-h-80 overflow-auto bg-white text-xs leading-5">
            {parseUnifiedDiff(f.diff).map((l: DiffLine, i: number) => (
              <div key={i} className={lineClass(l.type)}>
                {l.text || " "}
              </div>
            ))}
          </pre>
        </div>
      ))}
    </div>
  );
}

function lineClass(type: DiffLine["type"]): string {
  switch (type) {
    case "add":
      return "bg-green-50 px-2 text-green-800";
    case "del":
      return "bg-red-50 px-2 text-red-800";
    case "hunk":
      return "bg-slate-100 px-2 text-slate-500";
    case "meta":
      return "px-2 text-slate-400";
    default:
      return "px-2 text-slate-700";
  }
}
