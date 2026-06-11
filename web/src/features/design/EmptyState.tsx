import { useState } from "react";
import { Spinner } from "../../components/Spinner";
import { useCreateDoc } from "../../lib/queries";

// First doc = the project spec. Until it exists, Design shows this focused prompt.
export function EmptyState({ onCreated }: { onCreated: (id: string) => void }) {
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useCreateDoc();

  const submit = async () => {
    if (!prompt.trim()) return;
    setError(null);
    try {
      const entry = await create.mutateAsync({
        prompt: prompt.trim(),
        type: "project_spec",
      });
      onCreated(entry.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate project spec");
    }
  };

  return (
    <div className="mx-auto flex h-full max-w-xl flex-col justify-center px-6">
      <h2 className="text-2xl font-semibold text-slate-900">
        Describe your project
      </h2>
      <p className="mt-2 text-slate-500">
        What is it, and what's it for? The AI will draft your project spec
        (<code>project.md</code>) — the foundation everything else builds on.
      </p>
      <textarea
        className="mt-4 h-40 w-full resize-none rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="e.g. A web app that helps users design, plan, and build software with AI…"
        autoFocus
      />
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      <button
        className="mt-3 inline-flex items-center justify-center gap-2 self-start rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        onClick={submit}
        disabled={create.isPending || !prompt.trim()}
      >
        {create.isPending && <Spinner />}
        {create.isPending ? "Generating…" : "Generate project spec"}
      </button>
    </div>
  );
}
