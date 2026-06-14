import { useEffect, useState } from "react";
import {
  useRepos,
  useSaveRepos,
  useSaveSettings,
  useSettings,
} from "../../lib/queries";
import type { ProjectRepo } from "../../lib/types";

// Per-project settings modal: default build instructions + the repo registry
// (additional repos a task can target; 10).
export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const { data: settings, isLoading } = useSettings();
  const { data: reposData } = useRepos();
  const saveSettings = useSaveSettings();
  const saveRepos = useSaveRepos();

  const [text, setText] = useState("");
  const [repos, setRepos] = useState<ProjectRepo[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (settings) setText(settings.instructions);
  }, [settings]);
  useEffect(() => {
    if (reposData) setRepos(reposData.repos);
  }, [reposData]);

  const instructionsDirty = settings ? text !== settings.instructions : text !== "";
  const reposDirty = reposData
    ? JSON.stringify(repos) !== JSON.stringify(reposData.repos)
    : false;
  const dirty = instructionsDirty || reposDirty;
  const pending = saveSettings.isPending || saveRepos.isPending;

  const addRepo = () =>
    setRepos((rs) => [
      ...rs,
      { id: "", name: "", url: "", defaultBranch: "", primary: false },
    ]);
  const updateRepo = (i: number, patch: Partial<ProjectRepo>) =>
    setRepos((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const removeRepo = (i: number) => setRepos((rs) => rs.filter((_, j) => j !== i));

  async function handleSave() {
    setError(null);
    // Validate additional repos before sending (backend also enforces).
    for (const r of repos) {
      if (!r.primary && (!r.name.trim() || !r.url.trim())) {
        setError("Each additional repo needs a name and a clone URL.");
        return;
      }
    }
    try {
      if (reposDirty) await saveRepos.mutateAsync({ repos });
      if (instructionsDirty) await saveSettings.mutateAsync({ instructions: text });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl"
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

        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-auto px-5 py-4">
          <section className="flex flex-col gap-2">
            <label className="text-sm font-medium text-slate-700">
              Default task instructions
            </label>
            <p className="text-xs text-slate-500">
              Directions the AI follows for every task in this project (added to both the
              planning and build prompts). E.g. “Always run{" "}
              <code className="rounded bg-slate-100 px-1">npm run build</code> and the test
              suite before reporting a task done.”
            </p>
            <textarea
              className="min-h-[8rem] w-full resize-y rounded-md border border-slate-300 px-3 py-2 font-mono text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-300"
              placeholder={isLoading ? "Loading…" : "e.g. Run `npm run build` before reporting done."}
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={isLoading}
            />
          </section>

          <section className="flex flex-col gap-2">
            <label className="text-sm font-medium text-slate-700">Repositories</label>
            <p className="text-xs text-slate-500">
              Repos a task can target. The primary repo is this project's own repo;
              additional repos are cloned into the workspace so the AI has cross-repo
              context. A task writes to (and opens a PR against) the one repo it targets.
            </p>
            <div className="flex flex-col gap-2">
              {repos.map((r, i) =>
                r.primary ? (
                  <div
                    key="primary"
                    className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
                  >
                    <span className="font-medium text-slate-700">{r.name}</span>
                    <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[11px] text-slate-600">
                      primary
                    </span>
                    <span className="ml-auto text-xs text-slate-400">this project's repo</span>
                  </div>
                ) : (
                  <div key={i} className="flex items-center gap-2">
                    <input
                      className="w-32 rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-blue-400 focus:outline-none"
                      placeholder="name"
                      value={r.name}
                      onChange={(e) => updateRepo(i, { name: e.target.value })}
                    />
                    <input
                      className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs focus:border-blue-400 focus:outline-none"
                      placeholder="https://github.com/org/repo.git"
                      value={r.url}
                      onChange={(e) => updateRepo(i, { url: e.target.value })}
                    />
                    <button
                      className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                      onClick={() => removeRepo(i)}
                      title="Remove repo"
                    >
                      ✕
                    </button>
                  </div>
                ),
              )}
            </div>
            <button
              className="self-start rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
              onClick={addRepo}
            >
              + Add repository
            </button>
          </section>

          {error && <p className="text-sm text-red-600">{error}</p>}
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
            disabled={!dirty || pending}
          >
            {pending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
