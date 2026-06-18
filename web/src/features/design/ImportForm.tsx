import { useState } from "react";
import { Spinner } from "../../components/Spinner";
import { useImportDoc } from "../../lib/queries";
import type { DocType } from "../../lib/types";

type Item = { name: string; body: string };

// Shared import body (no Modal chrome): upload one or more .md files, or paste a
// single document. Each file becomes its own entry, written verbatim (05). Used
// by AddEntryDialog (doc/task) and ImportDialog (project spec).
export function ImportForm({
  type,
  onImported,
  onCancel,
}: {
  type: DocType;
  onImported: (id: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<Item[]>([]);
  const [error, setError] = useState<string | null>(null);
  const importDoc = useImportDoc();

  const onFiles = async (list: FileList | null) => {
    if (!list || list.length === 0) return;
    const read = await Promise.all(
      Array.from(list).map(async (f) => ({
        name: f.name.replace(/\.mdx?$/i, ""),
        body: await f.text(),
      })),
    );
    setFiles((prev) => [...prev, ...read]);
  };

  // Files (if any) take precedence; otherwise the single paste entry.
  const items: Item[] =
    files.length > 0
      ? files
      : name.trim() && body.trim()
        ? [{ name: name.trim(), body }]
        : [];

  const submit = async () => {
    if (items.length === 0) return;
    setError(null);
    try {
      let lastId = "";
      const failed: string[] = [];
      for (const it of items) {
        try {
          const entry = await importDoc.mutateAsync({ name: it.name, type, body: it.body });
          lastId = entry.id;
        } catch {
          failed.push(it.name);
        }
      }
      if (failed.length) {
        setError(`Failed to import: ${failed.join(", ")}`);
        return;
      }
      if (lastId) onImported(lastId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    }
  };

  const placeholderName =
    type === "project_spec" ? "Project spec" : type === "task" ? "Task name" : "Document name";

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-slate-700">
        Upload .md file(s)
        <input
          type="file"
          multiple
          accept=".md,.mdx,text/markdown"
          className="mt-1 block w-full text-sm text-slate-600"
          onChange={(e) => {
            void onFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </label>

      {files.length > 0 ? (
        <ul className="space-y-1 rounded-md border border-slate-200 bg-slate-50 p-2 text-sm">
          {files.map((f, i) => (
            <li key={i} className="flex items-center justify-between gap-2">
              <span className="truncate text-slate-700">{f.name}</span>
              <button
                className="text-xs text-slate-400 hover:text-red-600"
                onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <>
          <label className="block text-sm font-medium text-slate-700">
            Name
            <input
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={placeholderName}
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            …or paste content
            <textarea
              className="mt-1 h-40 w-full resize-none rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-blue-500 focus:outline-none"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="# My document…"
            />
          </label>
        </>
      )}

      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          className="rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
          onClick={onCancel}
          disabled={importDoc.isPending}
        >
          Cancel
        </button>
        <button
          className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          onClick={submit}
          disabled={importDoc.isPending || items.length === 0}
        >
          {importDoc.isPending && <Spinner />}
          {items.length > 1 ? `Import ${items.length}` : "Import"}
        </button>
      </div>
    </div>
  );
}
