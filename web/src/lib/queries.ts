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
