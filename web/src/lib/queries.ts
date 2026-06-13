// React Query hooks (04). Query keys include the active project so switching
// projects naturally refetches.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api, type Collection } from "./api";
import { useUiStore } from "../store";
import type { CommentAnchor, DocType, TaskStatus } from "./types";

const useProject = () => useUiStore((s) => s.activeProject);

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, root }: { name: string; root: string }) =>
      api.createProject(name, root),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useDocs() {
  const project = useProject();
  return useQuery({
    queryKey: ["docs", project],
    queryFn: api.listDocs,
    enabled: !!project,
  });
}

export function useDoc(id: string | null) {
  const project = useProject();
  return useQuery({
    queryKey: ["doc", project, id],
    queryFn: () => api.getDoc(id!),
    enabled: !!project && !!id,
  });
}

export function useTasks() {
  const project = useProject();
  return useQuery({
    queryKey: ["tasks", project],
    queryFn: api.listTasks,
    enabled: !!project,
  });
}

export function useTaskGraph() {
  const project = useProject();
  return useQuery({
    queryKey: ["taskGraph", project],
    queryFn: api.taskGraph,
    enabled: !!project,
  });
}

export function useCreateDoc() {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: ({
      prompt,
      type,
      name,
      dependsOn,
    }: {
      prompt: string;
      type: DocType;
      name?: string;
      dependsOn?: string[];
    }) => api.createDoc(prompt, type, name, dependsOn),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["docs", project] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useImportDoc() {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: ({ name, type, body }: { name: string; type: DocType; body: string }) =>
      api.importDoc(name, type, body),
    onSuccess: (_data, { type }) => {
      if (type === "task") {
        qc.invalidateQueries({ queryKey: ["tasks", project] });
        qc.invalidateQueries({ queryKey: ["taskGraph", project] });
      } else {
        qc.invalidateQueries({ queryKey: ["docs", project] });
      }
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useGenerateTasksFromSpec() {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: () => api.generateTasksFromSpec(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", project] });
      qc.invalidateQueries({ queryKey: ["taskGraph", project] });
    },
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: ({
      prompt,
      name,
      dependsOn,
      taskGroup,
    }: {
      prompt: string;
      name?: string;
      dependsOn?: string[];
      taskGroup?: string;
    }) => api.createTask(prompt, name, dependsOn, taskGroup),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", project] });
      qc.invalidateQueries({ queryKey: ["taskGraph", project] });
    },
  });
}

// ── Design-tab: collection-based entry hooks ──────────────────────────────────

export function useEntry(collection: Collection, id: string | null) {
  const project = useProject();
  return useQuery({
    queryKey: ["entry", project, collection, id],
    queryFn: () => api.getEntry(collection, id!),
    enabled: !!project && !!id,
  });
}

function useEntryInvalidator() {
  const qc = useQueryClient();
  const project = useProject();
  return (collection: Collection, id: string) => {
    qc.invalidateQueries({ queryKey: ["entry", project, collection, id] });
    qc.invalidateQueries({ queryKey: [collection === "tasks" ? "tasks" : "docs", project] });
  };
}

export function useSaveEntry() {
  const invalidate = useEntryInvalidator();
  return useMutation({
    mutationFn: ({ collection, id, body }: { collection: Collection; id: string; body: string }) =>
      api.saveEntry(collection, id, body),
    onSuccess: (_d, v) => invalidate(v.collection, v.id),
  });
}

export function useAddComment() {
  const invalidate = useEntryInvalidator();
  return useMutation({
    mutationFn: ({
      collection,
      id,
      anchor,
      body,
      kind,
    }: {
      collection: Collection;
      id: string;
      anchor: CommentAnchor;
      body: string;
      kind: string;
    }) => api.addComment(collection, id, anchor, body, kind),
    onSuccess: (_d, v) => invalidate(v.collection, v.id),
  });
}

export function useUpdateComment() {
  const invalidate = useEntryInvalidator();
  return useMutation({
    mutationFn: ({
      collection,
      id,
      commentId,
      patch,
    }: {
      collection: Collection;
      id: string;
      commentId: string;
      patch: { body?: string; resolved?: boolean };
    }) => api.updateComment(collection, id, commentId, patch),
    onSuccess: (_d, v) => invalidate(v.collection, v.id),
  });
}

export function usePatchMetadata() {
  const invalidate = useEntryInvalidator();
  return useMutation({
    mutationFn: ({
      collection,
      id,
      patch,
    }: {
      collection: Collection;
      id: string;
      patch: Record<string, unknown>;
    }) => api.patchMetadata(collection, id, patch),
    onSuccess: (_d, v) => invalidate(v.collection, v.id),
  });
}

export function useChat(collection: Collection, id: string | null) {
  const project = useProject();
  return useQuery({
    queryKey: ["chat", project, collection, id],
    queryFn: () => api.getChat(collection, id!),
    enabled: !!project && !!id,
  });
}

export function useSendChat() {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: ({
      collection,
      id,
      message,
    }: {
      collection: Collection;
      id: string;
      message: string;
    }) => api.sendChat(collection, id, message),
    onSuccess: (_d, v) => {
      // Reflect the new user message + the now-running operation immediately;
      // the assistant reply + body change arrive via the operations stream.
      qc.invalidateQueries({ queryKey: ["chat", project, v.collection, v.id] });
      qc.invalidateQueries({ queryKey: ["entry", project, v.collection, v.id] });
      qc.invalidateQueries({
        queryKey: [v.collection === "tasks" ? "tasks" : "docs", project],
      });
    },
  });
}

export function useSetTaskStatus() {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: TaskStatus }) =>
      api.setTaskStatus(id, status),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", project] });
      qc.invalidateQueries({ queryKey: ["taskGraph", project] });
    },
  });
}

// ── Build tab: executions ─────────────────────────────────────────────────────

export function useExecution(executionId: string | null) {
  const project = useProject();
  return useQuery({
    queryKey: ["execution", project, executionId],
    queryFn: () => api.getProgress(executionId!),
    enabled: !!project && !!executionId,
  });
}

// Liveness monitor: while a run shows `running`, poll the backend (on mount/visit +
// interval). The backend resumes the session if its process died, or marks it failed
// if it can't. We write the returned ProgressState into the execution cache, and
// refresh the task lists when it lands on a terminal status.
export function useExecutionMonitor(executionId: string | null, isRunning: boolean) {
  const qc = useQueryClient();
  const project = useProject();
  return useQuery({
    queryKey: ["executionMonitor", project, executionId],
    queryFn: async () => {
      const state = await api.ensureRunning(executionId!);
      qc.setQueryData(["execution", project, executionId], state);
      if (state.status !== "running" && state.status !== "awaiting_input") {
        qc.invalidateQueries({ queryKey: ["tasks", project] });
        qc.invalidateQueries({ queryKey: ["taskGraph", project] });
      }
      return state;
    },
    enabled: !!project && !!executionId && isRunning,
    refetchInterval: 15000,
    refetchOnWindowFocus: true,
    refetchOnMount: "always",
    staleTime: 0,
  });
}

// Mutations that change a run's progress: cache the returned ProgressState and
// refresh the task lists (task status flips with the run: in_progress/in_review).
function useExecutionMutation<V>(
  fn: (v: V) => Promise<import("./types").ProgressState>,
) {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: fn,
    onSuccess: (state) => {
      qc.setQueryData(["execution", project, state.executionId], state);
      qc.invalidateQueries({ queryKey: ["tasks", project] });
      qc.invalidateQueries({ queryKey: ["taskGraph", project] });
    },
  });
}

export function useStartExecution() {
  return useExecutionMutation(({ taskId }: { taskId: string }) =>
    api.startExecution(taskId),
  );
}

export function useAnswerQuestion() {
  return useExecutionMutation(
    ({ id, questionId, answer }: { id: string; questionId: string; answer: string }) =>
      api.answerQuestion(id, questionId, answer),
  );
}

export function useDecidePermission() {
  return useExecutionMutation(
    ({ id, requestId, decision }: { id: string; requestId: string; decision: "allow" | "deny" }) =>
      api.decidePermission(id, requestId, decision),
  );
}

export function useSendFeedback() {
  return useExecutionMutation(({ id, message }: { id: string; message: string }) =>
    api.sendFeedback(id, message),
  );
}

export function useCancelExecution() {
  return useExecutionMutation(({ id }: { id: string }) => api.cancelExecution(id));
}

export function useCreatePr() {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: ({ id }: { id: string }) => api.createPr(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks", project] });
    },
  });
}

export function useDiff(executionId: string | null) {
  const project = useProject();
  return useQuery({
    queryKey: ["diff", project, executionId],
    queryFn: () => api.getDiff(executionId!),
    enabled: !!project && !!executionId,
  });
}

export function useDiffComments(executionId: string | null) {
  const project = useProject();
  return useQuery({
    queryKey: ["diffComments", project, executionId],
    queryFn: () => api.getDiffComments(executionId!),
    enabled: !!project && !!executionId,
  });
}

export function useAddDiffComment() {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: ({
      id,
      comment,
    }: {
      id: string;
      comment: {
        commit: string;
        file: string;
        side: "new" | "old";
        lineStart: number;
        lineEnd: number;
        body: string;
      };
    }) => api.addDiffComment(id, comment),
    onSuccess: (_d, v) =>
      qc.invalidateQueries({ queryKey: ["diffComments", project, v.id] }),
  });
}

export function useUpdateDiffComment() {
  const qc = useQueryClient();
  const project = useProject();
  return useMutation({
    mutationFn: ({
      id,
      commentId,
      patch,
    }: {
      id: string;
      commentId: string;
      patch: { resolved?: boolean; body?: string };
    }) => api.updateDiffComment(id, commentId, patch),
    onSuccess: (_d, v) =>
      qc.invalidateQueries({ queryKey: ["diffComments", project, v.id] }),
  });
}
