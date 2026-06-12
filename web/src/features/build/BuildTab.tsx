import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTasks } from "../../lib/queries";
import { useUiStore } from "../../store";
import { BuildSidebar } from "./BuildSidebar";
import { InfoView } from "./InfoView";
import { DiffView } from "./DiffView";

// Build tab (08): task sidebar + main view that toggles Info / Diff for the
// selected task. The selected task lives in the route (/build/:taskId) and the
// ui store (shared with Plan).
export function BuildTab() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const project = useUiStore((s) => s.activeProject);
  const setSelectedTaskId = useUiStore((s) => s.setSelectedTaskId);
  const { data: tasks } = useTasks();
  const [view, setView] = useState<"info" | "diff">("info");

  useEffect(() => {
    setSelectedTaskId(taskId ?? null);
  }, [taskId, setSelectedTaskId]);

  const selected = tasks?.find((t) => t.id === taskId) ?? null;
  const executionId = selected?.executionId ?? null;
  const effectiveView = executionId ? view : "info";

  const select = (id: string) =>
    navigate(`/p/${encodeURIComponent(project ?? "")}/build/${id}`);

  return (
    <div className="flex h-full">
      <BuildSidebar selectedId={taskId ?? null} onSelect={select} />
      <div className="flex min-w-0 flex-1 flex-col">
        {!selected ? (
          <div className="flex h-full items-center justify-center text-slate-400">
            Select a task to run or review.
          </div>
        ) : (
          <>
            <header className="flex items-center gap-2 border-b border-slate-200 px-4 py-2">
              <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800">
                {selected.name}
              </h2>
              <div className="flex overflow-hidden rounded-md border border-slate-300 text-sm">
                <ToggleButton active={effectiveView === "info"} onClick={() => setView("info")}>
                  Info
                </ToggleButton>
                <ToggleButton
                  active={effectiveView === "diff"}
                  disabled={!executionId}
                  onClick={() => executionId && setView("diff")}
                >
                  Diff
                </ToggleButton>
              </div>
            </header>
            <div className="min-h-0 flex-1 overflow-auto">
              {effectiveView === "info" ? (
                <InfoView task={selected} />
              ) : (
                <DiffView executionId={executionId!} />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ToggleButton({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={`px-3 py-1 font-medium ${
        active ? "bg-blue-600 text-white" : "text-slate-600 hover:bg-slate-100"
      } ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
    >
      {children}
    </button>
  );
}
