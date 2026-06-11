import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { useCreateProject } from "../../lib/queries";
import { slugify } from "../../lib/slug";

export function CreateProjectModal({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [root, setRoot] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useCreateProject();
  const navigate = useNavigate();

  const preview = name && root ? `${root}/projects/${slugify(name)}/` : "";

  const submit = async () => {
    setError(null);
    try {
      const desc = await create.mutateAsync({ name: name.trim(), root: root.trim() });
      onOpenChange(false);
      setName("");
      setRoot("");
      navigate(`/p/${encodeURIComponent(desc.name)}/design`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create project");
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="New project"
      description="A project lives inside an existing git repository (the codebase root)."
    >
      <div className="space-y-3">
        <label className="block text-sm font-medium text-slate-700">
          Project name
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My App"
            autoFocus
          />
        </label>
        <label className="block text-sm font-medium text-slate-700">
          Root directory (absolute path to a git repo)
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-blue-500 focus:outline-none"
            value={root}
            onChange={(e) => setRoot(e.target.value)}
            placeholder="/abs/path/to/codebase"
          />
        </label>
        {preview && (
          <p className="text-xs text-slate-500">
            Project files will live at <code className="text-slate-700">{preview}</code>
          </p>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button
            className="rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
            onClick={() => onOpenChange(false)}
            disabled={create.isPending}
          >
            Cancel
          </button>
          <button
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            onClick={submit}
            disabled={create.isPending || !name.trim() || !root.trim()}
          >
            {create.isPending && <Spinner />}
            Create
          </button>
        </div>
      </div>
    </Modal>
  );
}
