import { useState } from "react";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";
import type { MetadataEntry } from "../lib/types";

export interface PromptResult {
  prompt: string;
  name?: string;
  dependsOn: string[];
}

interface PromptDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  submitLabel?: string;
  busy?: boolean;
  error?: string | null;
  // When provided, render a dependency multi-select (used for tasks).
  dependencyOptions?: MetadataEntry[];
  onSubmit: (result: PromptResult) => void;
}

export function PromptDialog({
  open,
  onOpenChange,
  title,
  description,
  submitLabel = "Generate",
  busy = false,
  error,
  dependencyOptions,
  onSubmit,
}: PromptDialogProps) {
  const [prompt, setPrompt] = useState("");
  const [name, setName] = useState("");
  const [dependsOn, setDependsOn] = useState<string[]>([]);

  const toggleDep = (id: string) =>
    setDependsOn((cur) =>
      cur.includes(id) ? cur.filter((d) => d !== id) : [...cur, id],
    );

  const submit = () => {
    if (!prompt.trim() || busy) return;
    onSubmit({ prompt: prompt.trim(), name: name.trim() || undefined, dependsOn });
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title} description={description}>
      <div className="space-y-3">
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
            placeholder="Describe the document or task to generate…"
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
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            onClick={submit}
            disabled={busy || !prompt.trim()}
          >
            {busy && <Spinner />}
            {submitLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
