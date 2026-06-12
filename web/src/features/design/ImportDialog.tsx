import { useState } from "react";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { useImportDoc } from "../../lib/queries";
import type { DocType } from "../../lib/types";

type ImportKind = "doc" | "task";

type Item = { name: string; body: string };

// Import existing docs/tasks without AI: paste Markdown or upload one or more
// .md files. Each file becomes its own entry, written verbatim (05).
export function ImportDialog({
  open,
  onOpenChange,
  onImported,
  fixedType,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: (id: string) => void;
  // When set (e.g. the project-spec empty state), hide the type selector and
  // import as this type instead of doc/task.
  fixedType?: DocType;
}) {
  const [kind, setKind] = useState<ImportKind>("doc");
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<Item[]>([]);
  const [error, setError] = useState<string | null>(null);
  const importDoc = useImportDoc();

  const reset = () => {
    setName("");
    setBody("");
    setFiles([]);
    setError(null);
  };

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
    const type: DocType = fixedType ?? (kind === "task" ? "task" : "doc");
    try {
      let lastId = "";
      for (const it of items) {
        const entry = await importDoc.mutateAsync({ name: it.name, type, body: it.body });
        lastId = entry.id;
      }
      onOpenChange(false);
      reset();
      if (lastId) onImported(lastId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
      title={fixedType === "project_spec" ? "Import project spec" : "Import"}
      description="Upload one or more .md files, or paste a single document. No AI — content is saved as-is."
    >
      <div className="space-y-3">
        {!fixedType && (
          <div>
            <div className="mb-1 text-sm font-medium text-slate-700">Type</div>
            <div className="flex gap-1">
              <KindBtn active={kind === "doc"} onClick={() => setKind("doc")}>
                Document
              </KindBtn>
              <KindBtn active={kind === "task"} onClick={() => setKind("task")}>
                Task
              </KindBtn>
            </div>
          </div>
        )}

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
                placeholder={
                  fixedType === "project_spec"
                    ? "Project spec"
                    : kind === "task"
                      ? "Task name"
                      : "Document name"
                }
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
            onClick={() => onOpenChange(false)}
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
    </Modal>
  );
}

function KindBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      className={`rounded-md px-3 py-1.5 text-sm font-medium ${
        active ? "bg-blue-100 text-blue-700" : "text-slate-600 hover:bg-slate-100"
      }`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
