import { useState } from "react";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { useCreateDoc, useCreateTask } from "../../lib/queries";
import type { MetadataEntry } from "../../lib/types";
import { ImportForm } from "./ImportForm";

type Mode = "generate" | "import";

// Unified "new doc / new task" modal: a Generate-with-AI tab and an Import tab
// (paste or upload .md files). Replaces the separate sidebar Import button.
export function AddEntryDialog({
  open,
  onOpenChange,
  kind,
  dependencyOptions,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kind: "doc" | "task";
  dependencyOptions?: MetadataEntry[];
  onCreated: (id: string) => void;
}) {
  const [mode, setMode] = useState<Mode>("generate");
  const [prompt, setPrompt] = useState("");
  const [name, setName] = useState("");
  const [dependsOn, setDependsOn] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const createDoc = useCreateDoc();
  const createTask = useCreateTask();
  const busy = createDoc.isPending || createTask.isPending;

  const reset = () => {
    setMode("generate");
    setPrompt("");
    setName("");
    setDependsOn([]);
    setError(null);
  };

  const close = (o: boolean) => {
    if (!o) reset();
    onOpenChange(o);
  };

  const done = (id: string) => {
    close(false);
    onCreated(id);
  };

  const toggleDep = (id: string) =>
    setDependsOn((cur) =>
      cur.includes(id) ? cur.filter((d) => d !== id) : [...cur, id],
    );

  const generate = async () => {
    if (!prompt.trim() || busy) return;
    setError(null);
    try {
      const entry =
        kind === "task"
          ? await createTask.mutateAsync({
              prompt: prompt.trim(),
              name: name.trim() || undefined,
              dependsOn,
            })
          : await createDoc.mutateAsync({
              prompt: prompt.trim(),
              type: "doc",
              name: name.trim() || undefined,
            });
      done(entry.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={close}
      title={kind === "task" ? "New task" : "New document"}
    >
      <div className="space-y-3">
        <div className="flex gap-1 rounded-md bg-slate-100 p-1">
          <Tab active={mode === "generate"} onClick={() => setMode("generate")}>
            Generate with AI
          </Tab>
          <Tab active={mode === "import"} onClick={() => setMode("import")}>
            Import
          </Tab>
        </div>

        {mode === "generate" ? (
          <>
            <label className="block text-sm font-medium text-slate-700">
              Name <span className="font-normal text-slate-400">(optional)</span>
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Let AI choose if blank"
              />
            </label>

            <label className="block text-sm font-medium text-slate-700">
              What should the AI create?
              <textarea
                className="mt-1 h-32 w-full resize-none rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder={`Describe the ${kind} to generate…`}
                autoFocus
              />
            </label>

            {dependencyOptions && dependencyOptions.length > 0 && (
              <div className="text-sm">
                <div className="mb-1 font-medium text-slate-700">Depends on</div>
                <div className="max-h-32 space-y-1 overflow-auto rounded-md border border-slate-200 p-2">
                  {dependencyOptions.map((opt) => (
                    <label key={opt.id} className="flex items-center gap-2 text-slate-600">
                      <input
                        type="checkbox"
                        checked={dependsOn.includes(opt.id)}
                        onChange={() => toggleDep(opt.id)}
                      />
                      {opt.name}
                    </label>
                  ))}
                </div>
              </div>
            )}

            {error && <p className="text-sm text-red-600">{error}</p>}

            <div className="flex justify-end gap-2 pt-1">
              <button
                className="rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
                onClick={() => close(false)}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                onClick={generate}
                disabled={busy || !prompt.trim()}
              >
                {busy && <Spinner />}
                Generate
              </button>
            </div>
          </>
        ) : (
          <ImportForm
            type={kind}
            onImported={done}
            onCancel={() => close(false)}
          />
        )}
      </div>
    </Modal>
  );
}

function Tab({
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
      className={`flex-1 rounded px-3 py-1.5 text-sm font-medium ${
        active ? "bg-white text-slate-800 shadow-sm" : "text-slate-500 hover:text-slate-700"
      }`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
