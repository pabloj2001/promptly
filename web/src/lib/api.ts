// Typed fetch client. Auto-attaches the active project as ?project= and
// normalizes the API's { error: { code, message } } envelope (02).

import { getActiveProject } from "../store";
import type {
  AddressResponse,
  ChatHistory,
  ChatMessage,
  Comment,
  CommentAnchor,
  DependencyGraph,
  DocOut,
  DocType,
  MetadataEntry,
  PermissionsConfig,
  ProgressState,
  ProjectDescriptor,
  TaskStatus,
} from "./types";

// A "collection" mirrors the backend: tasks use /tasks/*, everything else /docs/*.
export type Collection = "docs" | "tasks";

const BASE = "/api";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

interface RequestOpts {
  method?: string;
  body?: unknown;
  // When true, attach the active project as ?project=.
  scoped?: boolean;
  query?: Record<string, string | undefined>;
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const { method = "GET", body, scoped = false, query = {} } = opts;
  const params = new URLSearchParams();
  if (scoped) {
    const project = getActiveProject();
    if (!project) throw new ApiError("no_project", "no active project", 400);
    params.set("project", project);
  }
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined) params.set(k, v);
  }
  const qs = params.toString();
  const res = await fetch(`${BASE}${path}${qs ? `?${qs}` : ""}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    const code = data?.error?.code ?? "http_error";
    const message = data?.error?.message ?? res.statusText;
    throw new ApiError(code, message, res.status);
  }
  return data as T;
}

export const api = {
  // Projects
  listProjects: () => request<ProjectDescriptor[]>("/projects"),
  getProject: (name: string) =>
    request<ProjectDescriptor>(`/projects/${encodeURIComponent(name)}`),
  createProject: (name: string, root: string) =>
    request<ProjectDescriptor>("/projects", { method: "POST", body: { name, root } }),
  deleteProject: (name: string) =>
    request<void>(`/projects/${encodeURIComponent(name)}`, { method: "DELETE" }),

  // Docs
  listDocs: () => request<MetadataEntry[]>("/docs", { scoped: true }),
  getDoc: (id: string) => request<DocOut>(`/docs/${id}`, { scoped: true }),
  createDoc: (prompt: string, type: DocType, name?: string, dependsOn: string[] = []) =>
    request<MetadataEntry>("/docs", {
      method: "POST",
      scoped: true,
      body: { prompt, type, name, dependsOn },
    }),
  saveDoc: (id: string, body: string) =>
    request<MetadataEntry>(`/docs/${id}`, { method: "PUT", scoped: true, body: { body } }),
  addDocComment: (id: string, anchor: Comment["anchor"], body: string, kind = "comment") =>
    request<Comment>(`/docs/${id}/comments`, {
      method: "POST",
      scoped: true,
      body: { anchor, body, kind },
    }),
  deleteDoc: (id: string) =>
    request<MetadataEntry>(`/docs/${id}`, { method: "DELETE", scoped: true }),

  // Tasks
  listTasks: () => request<MetadataEntry[]>("/tasks", { scoped: true }),
  getTask: (id: string) => request<DocOut>(`/tasks/${id}`, { scoped: true }),
  taskGraph: () => request<DependencyGraph>("/tasks/graph", { scoped: true }),
  createTask: (prompt: string, name?: string, dependsOn: string[] = [], taskGroup?: string) =>
    request<MetadataEntry>("/tasks", {
      method: "POST",
      scoped: true,
      body: { prompt, name, dependsOn, taskGroup },
    }),
  setTaskStatus: (id: string, status: TaskStatus) =>
    request<MetadataEntry>(`/tasks/${id}/status`, {
      method: "PUT",
      scoped: true,
      body: { status },
    }),
  patchTaskMetadata: (id: string, patch: Record<string, unknown>) =>
    request<MetadataEntry>(`/tasks/${id}/metadata`, {
      method: "PUT",
      scoped: true,
      body: patch,
    }),
  patchDocMetadata: (id: string, patch: Record<string, unknown>) =>
    request<MetadataEntry>(`/docs/${id}/metadata`, {
      method: "PUT",
      scoped: true,
      body: patch,
    }),

  // Unified by collection (Design tab treats docs + task specs uniformly).
  getEntry: (collection: Collection, id: string) =>
    request<DocOut>(`/${collection}/${id}`, { scoped: true }),
  saveEntry: (collection: Collection, id: string, body: string) =>
    request<MetadataEntry>(`/${collection}/${id}`, {
      method: "PUT",
      scoped: true,
      body: { body },
    }),
  addComment: (
    collection: Collection,
    id: string,
    anchor: CommentAnchor,
    body: string,
    kind = "comment",
  ) =>
    request<Comment>(`/${collection}/${id}/comments`, {
      method: "POST",
      scoped: true,
      body: { anchor, body, kind },
    }),
  updateComment: (
    collection: Collection,
    id: string,
    commentId: string,
    patch: { body?: string; resolved?: boolean },
  ) =>
    request<Comment>(`/${collection}/${id}/comments/${commentId}`, {
      method: "PUT",
      scoped: true,
      body: patch,
    }),
  getChat: (collection: Collection, id: string) =>
    request<ChatHistory>(`/${collection}/${id}/chat`, { scoped: true }),
  sendChat: (collection: Collection, id: string, message: string) =>
    request<ChatMessage>(`/${collection}/${id}/chat`, {
      method: "POST",
      scoped: true,
      body: { message },
    }),
  getPermissions: () => request<PermissionsConfig>("/permissions", { scoped: true }),
  putPermissions: (config: PermissionsConfig) =>
    request<PermissionsConfig>("/permissions", {
      method: "PUT",
      scoped: true,
      body: config,
    }),
  address: (collection: Collection, id: string) =>
    request<AddressResponse>(`/${collection}/${id}/address`, {
      method: "POST",
      scoped: true,
    }),
  patchMetadata: (collection: Collection, id: string, patch: Record<string, unknown>) =>
    request<MetadataEntry>(`/${collection}/${id}/metadata`, {
      method: "PUT",
      scoped: true,
      body: patch,
    }),

  // Executions
  getProgress: (id: string) =>
    request<ProgressState>(`/executions/${id}`, { scoped: true }),
  startExecution: (taskId: string) =>
    request<ProgressState>("/executions", {
      method: "POST",
      scoped: true,
      body: { taskId },
    }),
};
