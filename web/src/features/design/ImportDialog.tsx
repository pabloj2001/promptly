import { useState } from "react";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { useImportDoc } from "../../lib/queries";
import type { DocType } from "../../lib/types";

// Import an existing doc without AI: paste Markdown or upload a .md file (05).
export function ImportDialog({
  open,
  onOpenChange,
  type,
  onImported,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  type: DocType; // "doc" | "project_spec"
  onImported: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const importDoc = useImportDoc();

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    const text = await file.text();
    setBody(text);
    if (!name.trim()) setName(file.name.replace(/\.mdx?$/i, ""));
  };

  const submit = async () => {
    if (!name.trim() || !body.trim()) return;
    setError(null);
    try {
      const entry = await importDoc.mutateAsync({ name: name.trim(), type, body });
      onOpenChange(false);
      setName("");
      setBody("");
      onImported(entry.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={type === "project_spec" ? "Import project spec" : "Import document"}
      description="Paste Markdown or upload a .md file. No AI — the content is saved as-is."
    >
      <div className="space-y-3">
        <label className="block text-sm font-medium text-slate-700">
          Name
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={type === "project_spec" ? "Project spec" : "Document name"}
          />
        </label>
        <label className="block text-sm font-medium text-slate-700">
          Upload a .md file
          <input
            type="file"
            accept=".md,.mdx,text/markdown"
            className="mt-1 block w-full text-sm text-slate-600"
            onChange={(e) => onFile(e.target.files?.[0])}
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
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
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
            disabled={importDoc.isPending || !name.trim() || !body.trim()}
          >
            {importDoc.isPending && <Spinner />}
            Import
          </button>
        </div>
      </div>
    </Modal>
  );
}
