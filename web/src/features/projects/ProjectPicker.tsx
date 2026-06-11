import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProjects } from "../../lib/queries";
import { Spinner } from "../../components/Spinner";
import { CreateProjectModal } from "./CreateProjectModal";

export function ProjectPicker() {
  const { data: projects, isLoading, error } = useProjects();
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  return (
    <div className="mx-auto max-w-2xl px-6 py-16">
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Promptly</h1>
          <p className="mt-1 text-slate-500">
            Design, plan, and build software projects with AI.
          </p>
        </div>
        <button
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          onClick={() => setCreating(true)}
        >
          New project
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-slate-500">
          <Spinner /> Loading projects…
        </div>
      )}
      {error && <p className="text-red-600">Failed to load projects.</p>}

      {projects && projects.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-slate-500">
          No projects yet. Create your first one to get started.
        </div>
      )}

      <ul className="space-y-2">
        {projects?.map((p) => (
          <li key={p.name}>
            <button
              className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-4 py-3 text-left hover:border-blue-400 hover:bg-blue-50"
              onClick={() => navigate(`/p/${encodeURIComponent(p.name)}/design`)}
            >
              <div>
                <div className="font-medium text-slate-900">{p.name}</div>
                <div className="font-mono text-xs text-slate-500">{p.root}</div>
              </div>
              <div className="text-xs text-slate-400">
                {p.hasProjectSpec ? "spec ✓" : "no spec yet"}
              </div>
            </button>
          </li>
        ))}
      </ul>

      <CreateProjectModal open={creating} onOpenChange={setCreating} />
    </div>
  );
}
