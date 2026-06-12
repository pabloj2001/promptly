import { useState } from "react";
import { PromptDialog, type PromptResult } from "../../components/PromptDialog";
import { Spinner } from "../../components/Spinner";
import { GenerateTasksButton } from "../../components/GenerateTasksButton";
import { useCreateTask, useTasks, useTaskGraph } from "../../lib/queries";
import { useOperationsStream } from "../../lib/sse";
import { useUiStore } from "../../store";
import { GraphView } from "./GraphView";
import { BoardView } from "./BoardView";
import { TaskSidePanel } from "./TaskSidePanel";

export function PlanTab() {
  const planView = useUiStore((s) => s.planView);
  const setPlanView = useUiStore((s) => s.setPlanView);
  const selectedTaskId = useUiStore((s) => s.selectedTaskId);
  const setSelectedTaskId = useUiStore((s) => s.setSelectedTaskId);

  const { data: graph, isLoading } = useTaskGraph();
  const { data: tasks } = useTasks();
  const createTask = useCreateTask();
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useOperationsStream(); // live updates as generated tasks finalize

  const visibleTasks = (tasks ?? []).filter((t) => t.status !== "removed");

  const submitNew = async (r: PromptResult) => {
    setError(null);
    try {
      const entry = await createTask.mutateAsync({
        prompt: r.prompt,
        name: r.name,
        dependsOn: r.dependsOn,
      });
      setAdding(false);
      setSelectedTaskId(entry.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create task");
    }
  };

  return (
    <div className="relative flex h-full min-h-0">
      <div className="relative min-h-0 flex-1">
        {isLoading || !graph ? (
          <div className="flex h-full items-center justify-center text-slate-400">
            <Spinner />
          </div>
        ) : graph.nodes.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-400">
            <div>No tasks yet.</div>
            <GenerateTasksButton />
            <div className="text-xs">…or add one with the + button.</div>
          </div>
        ) : planView === "graph" ? (
          <GraphView graph={graph} onSelect={setSelectedTaskId} />
        ) : (
          <BoardView onSelect={setSelectedTaskId} />
        )}

        {/* Center-bottom view toggle */}
        <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center">
          <div className="pointer-events-auto flex gap-1 rounded-full border border-slate-200 bg-white p-1 shadow">
            <ToggleBtn active={planView === "graph"} onClick={() => setPlanView("graph")}>
              Graph
            </ToggleBtn>
            <ToggleBtn active={planView === "board"} onClick={() => setPlanView("board")}>
              Board
            </ToggleBtn>
          </div>
        </div>

        {/* Floating add-task */}
        <button
          className="absolute bottom-4 right-4 flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-2xl text-white shadow-lg hover:bg-blue-700"
          onClick={() => setAdding(true)}
          title="Add task"
        >
          +
        </button>
      </div>

      {selectedTaskId && (
        <TaskSidePanel
          taskId={selectedTaskId}
          onSelect={setSelectedTaskId}
          onClose={() => setSelectedTaskId(null)}
        />
      )}

      <PromptDialog
        open={adding}
        onOpenChange={(o) => !o && setAdding(false)}
        title="New task"
        description="Describe the task; the AI writes its spec."
        submitLabel="Generate"
        busy={createTask.isPending}
        error={error}
        dependencyOptions={visibleTasks}
        onSubmit={submitNew}
      />
    </div>
  );
}

function ToggleBtn({
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
      className={`rounded-full px-4 py-1 text-sm font-medium ${
        active ? "bg-blue-100 text-blue-700" : "text-slate-600 hover:bg-slate-100"
      }`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
