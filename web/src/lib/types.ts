// Shared types mirroring the API/01 schemas (camelCase on the wire).

export type DocType = "task" | "project_spec" | "doc";

export type TaskStatus =
  | "pending"
  | "in_progress"
  | "in_review"
  | "blocked"
  | "done"
  | "removed";

export type ProgressStatus = "running" | "awaiting_input" | "completed" | "failed";
export type StepStatus = "pending" | "in_progress" | "done" | "skipped";
export type CommentKind = "comment" | "question";

export interface ProjectDescriptor {
  name: string;
  root: string;
  lastOpenedAt?: string | null;
  hasProjectSpec: boolean;
}

export interface RelatedPR {
  url: string;
  number: number;
  state: string;
}

export type ExecutionKind = "task" | "doc";

export interface MetadataEntry {
  id: string;
  name: string;
  type: DocType;
  description: string;
  status?: TaskStatus | null;
  taskGroup?: string | null;
  relatedPrs: RelatedPR[];
  dependsOn: string[];
  custom: Record<string, unknown>;
  executionId?: string | null;
  // The doc-kind authoring execution for this entry (unified executions); reused for
  // follow-up / chat / comment-edits. executionId above is the task build.
  authoringExecutionId?: string | null;
  executionError?: boolean;
  executionBlocked?: boolean;
  repo?: string | null;
  file: string;
  createdAt: string;
  updatedAt: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  revisedBody: boolean;
  createdAt: string;
}

export interface ChatHistory {
  entryId: string;
  sessionId?: string | null;
  messages: ChatMessage[];
}

export interface PermissionProfile {
  permissionMode: string;
  allow: string[];
  deny: string[];
  askFallback: boolean;
}

export interface ProjectSettings {
  // Default directions appended to every build/plan prompt for this project.
  instructions: string;
}

export interface ProjectRepo {
  id: string;
  name: string;
  url: string;
  defaultBranch: string;
  primary: boolean;
}

export interface ProjectRepos {
  repos: ProjectRepo[];
}

export interface PermissionsConfig {
  version: number;
  additionalReadDirs: string[];
  generation: PermissionProfile;
  execution: PermissionProfile;
}

export interface CommentAnchor {
  quote: string;
  start: number;
  end: number;
}

export interface Comment {
  id: string;
  anchor: CommentAnchor;
  body: string;
  kind: CommentKind;
  author: string;
  resolved: boolean;
  orphaned: boolean;
  createdAt: string;
}

export interface DocOut {
  meta: MetadataEntry;
  body: string;
  comments: Comment[];
}

export interface GraphNode {
  id: string;
  name: string;
  status?: TaskStatus | null;
  taskGroup?: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface DependencyGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Question {
  id: string;
  question: string;
  answer?: string | null;
  kind?: "question" | "issue";
  askedAt: string;
}

export interface PermissionRequest {
  id: string;
  tool: string;
  request: Record<string, unknown>;
  decision?: string | null;
  askedAt: string;
}

export interface Step {
  id: string;
  title: string;
  detail: string;
  status: StepStatus;
  startedAt?: string | null;
  finishedAt?: string | null;
}

export interface ProgressState {
  executionId: string;
  taskId: string; // the entry this execution belongs to (task or doc id)
  collection: "docs" | "tasks";
  kind: ExecutionKind;
  branch?: string | null;
  baseSha?: string | null;
  sessionId?: string | null;
  status: ProgressStatus;
  error?: string | null;
  activity?: string | null;
  bodyBefore?: string | null;
  doneSummary?: string | null;
  pendingQuestions: Question[];
  pendingPermissions: PermissionRequest[];
  steps: Step[];
  createdAt: string;
  updatedAt: string;
}

export interface DiffFile {
  path: string;
  status: string; // git name-status code: A/M/D/R...
  diff: string; // unified patch text
}

export interface DiffResponse {
  baseSha: string;
  headSha: string;
  files: DiffFile[];
}

export interface DiffComment {
  id: string;
  file: string;
  side: "new" | "old";
  lineStart: number;
  lineEnd: number;
  body: string;
  author: string;
  resolved: boolean;
  createdAt: string;
}

export interface CommentsFile {
  byCommit: Record<string, DiffComment[]>;
}

export interface ApiError {
  error: { code: string; message: string };
}
