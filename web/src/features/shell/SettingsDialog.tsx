import { useEffect, useState } from "react";
import { useSaveSettings, useSettings } from "../../lib/queries";

// Per-project settings modal. Currently holds the default build instructions —
// directions the AI follows for every task in this project (e.g. "run the build
// before reporting done").
export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const { data, isLoading } = useSettings();
  const save = useSaveSettings();
  const [text, setText] = useState("");

  useEffect(() => {
    if (data) setText(data.instructions);
  }, [data]);

  const dirty = data ? text !== data.instructions : text !== "";

  async function handleSave() {
    await save.mutateAsync({ instructions: text });
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-800">Project settings</h2>
          <button
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto px-5 py-4">
          <label className="text-sm font-medium text-slate-700">
            Default task instructions
          </label>
          <p className="text-xs text-slate-500">
            Directions the AI follows for every task in this project. These are added to
            both the planning and build prompts. For example: “Always run{" "}
            <code className="rounded bg-slate-100 px-1">npm run build</code> and the test
            suite before reporting a task done.”
          </p>
          <textarea
            className="min-h-[12rem] w-full resize-y rounded-md border border-slate-300 px-3 py-2 font-mono text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-300"
            placeholder={isLoading ? "Loading…" : "e.g. Run `npm run build` before reporting done. Match existing code style."}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={isLoading}
          />
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-3">
          <button
            className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            onClick={handleSave}
            disabled={!dirty || save.isPending}
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
