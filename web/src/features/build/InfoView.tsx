import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useAnswerQuestion,
  useCancelExecution,
  useCreatePr,
  useDecidePermission,
  useExecution,
  useSendFeedback,
  useStartExecution,
  useTasks,
} from "../../lib/queries";
import { useExecutionStream } from "../../lib/sse";
import { useUiStore } from "../../store";
import { StatusBadge } from "../../components/StatusBadge";
import { Spinner } from "../../components/Spinner";
import type {
  MetadataEntry,
  PermissionRequest,
  ProgressState,
  Step,
} from "../../lib/types";

// Info view (08): status-driven run UI for the selected task.
export function InfoView({ task }: { task: MetadataEntry }) {
  const executionId = task.executionId ?? null;
  useExecutionStream(executionId);
  const { data: progress } = useExecution(executionId);
  const start = useStartExecution();

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-5">
      <TaskMeta task={task} />

      {!executionId ? (
        <section className="rounded-lg border border-slate-200 bg-white p-5 text-center">
          <p className="mb-3 text-sm text-slate-600">
            This task hasn't been built yet. Start an execution to create an isolated
            worktree and have Claude build it.
          </p>
          <button
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            disabled={start.isPending}
            onClick={() => start.mutate({ taskId: task.id })}
          >
            {start.isPending ? "Starting…" : "Begin execution"}
          </button>
          {start.isError && (
            <p className="mt-2 text-sm text-red-600">{(start.error as Error).message}</p>
          )}
        </section>
      ) : !progress ? (
        <p className="text-sm text-slate-400">Loading execution…</p>
      ) : (
        <RunBody task={task} progress={progress} executionId={executionId} />
      )}
    </div>
  );
}

function TaskMeta({ task }: { task: MetadataEntry }) {
  const { data: tasks } = useTasks();
  const navigate = useNavigate();
  const project = useUiStore((s) => s.activeProject);

  const deps = (task.dependsOn ?? []).map(
    (id) => tasks?.find((t) => t.id === id)?.name ?? id,
  );
  const custom = Object.entries(task.custom ?? {});
  const fmt = (s?: string) => (s ? new Date(s).toLocaleString() : "—");

  return (
    <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2">
        <StatusBadge status={task.status} />
        {task.taskGroup && (
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
            {task.taskGroup}
          </span>
        )}
        <button
          className="ml-auto rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
          onClick={() =>
            navigate(
              `/p/${encodeURIComponent(project ?? "")}/design?doc=${task.id}`,
            )
          }
        >
          Open in Design
        </button>
      </div>

      <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2 text-sm">
        <Field label="Description">{task.description || "—"}</Field>
        <Field label="Depends on">{deps.length ? deps.join(", ") : "None"}</Field>
        {custom.map(([k, v]) => (
          <Field key={k} label={k}>
            {String(v)}
          </Field>
        ))}
        <Field label="Created">{fmt(task.createdAt)}</Field>
        <Field label="Updated">{fmt(task.updatedAt)}</Field>
        <Field label="Execution">
          {task.executionId ? (
            <code className="text-xs text-slate-600">{task.executionId}</code>
          ) : (
            "Not started"
          )}
        </Field>
        {(task.relatedPrs ?? []).length > 0 && (
          <Field label="PRs">
            {task.relatedPrs.map((pr) => (
              <a
                key={pr.url}
                href={pr.url}
                target="_blank"
                rel="noreferrer"
                className="mr-3 text-blue-600 hover:underline"
              >
                #{pr.number} ({pr.state})
              </a>
            ))}
          </Field>
        )}
      </dl>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="min-w-0 break-words text-slate-700">{children}</dd>
    </>
  );
}

function RunBody({
  task,
  progress,
  executionId,
}: {
  task: MetadataEntry;
  progress: ProgressState;
  executionId: string;
}) {
  const cancel = useCancelExecution();
  const running = progress.status === "running";
  const awaiting = progress.status === "awaiting_input";
  const completed = progress.status === "completed";
  const failed = progress.status === "failed";

  const openQuestion = progress.pendingQuestions.find((q) => q.answer == null);
  const openPermissions = progress.pendingPermissions.filter((p) => p.decision == null);

  return (
    <div className="space-y-5">
      {running && (
        <div className="flex items-center gap-2 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-700">
          <Spinner /> Claude is working…
          <button
            className="ml-auto text-xs font-medium text-blue-700 underline hover:text-blue-900"
            onClick={() => cancel.mutate({ id: executionId })}
          >
            Cancel
          </button>
        </div>
      )}
      {failed && (
        <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          Execution failed{progress.error ? `: ${progress.error}` : "."} You can send
          feedback below to resume.
        </div>
      )}

      <Steps steps={progress.steps} planning={running} />

      {awaiting && openPermissions.length > 0 && (
        <Permissions executionId={executionId} requests={openPermissions} />
      )}
      {awaiting && !openPermissions.length && openQuestion && (
        <QuestionBox executionId={executionId} question={openQuestion} />
      )}

      {(completed || failed) && (
        <Review task={task} progress={progress} executionId={executionId} />
      )}
    </div>
  );
}

function Steps({ steps, planning }: { steps: Step[]; planning?: boolean }) {
  if (!steps.length)
    return (
      <p className="flex items-center gap-2 text-sm text-slate-400">
        {planning && <Spinner className="text-slate-400" />}
        {planning ? "Planning steps…" : "No steps reported yet."}
      </p>
    );
  const icon = (s: Step["status"]) =>
    s === "done" ? "✓" : s === "in_progress" ? "" : s === "skipped" ? "–" : "○";
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Steps
      </h3>
      <ol className="space-y-1">
        {steps.map((s) => (
          <li key={s.id} className="flex items-start gap-2 text-sm">
            <span className="mt-0.5 w-4 text-center text-slate-500">
              {s.status === "in_progress" ? <Spinner className="text-blue-500" /> : icon(s.status)}
            </span>
            <span className="flex-1">
              <span
                className={
                  s.status === "done"
                    ? "text-slate-500 line-through"
                    : s.status === "in_progress"
                      ? "font-medium text-slate-800"
                      : "text-slate-700"
                }
              >
                {s.title}
              </span>
              {s.detail && <span className="block text-xs text-slate-400">{s.detail}</span>}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function QuestionBox({
  executionId,
  question,
}: {
  executionId: string;
  question: { id: string; question: string };
}) {
  const [answer, setAnswer] = useState("");
  const answerQ = useAnswerQuestion();
  const submit = () => {
    if (!answer.trim()) return;
    answerQ.mutate({ id: executionId, questionId: question.id, answer: answer.trim() });
    setAnswer("");
  };
  return (
    <section className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <h3 className="mb-1 text-sm font-semibold text-amber-800">Claude has a question</h3>
      <p className="mb-3 text-sm text-slate-700">{question.question}</p>
      <textarea
        className="w-full rounded-md border border-slate-300 p-2 text-sm"
        rows={3}
        placeholder="Type your answer…"
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
      />
      <div className="mt-2 flex justify-end">
        <button
          className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
          disabled={answerQ.isPending || !answer.trim()}
          onClick={submit}
        >
          {answerQ.isPending ? "Sending…" : "Send answer"}
        </button>
      </div>
    </section>
  );
}

function Permissions({
  executionId,
  requests,
}: {
  executionId: string;
  requests: PermissionRequest[];
}) {
  const decide = useDecidePermission();
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-orange-800">Permission needed</h3>
      {requests.map((r) => (
        <div key={r.id} className="rounded-lg border border-orange-200 bg-orange-50 p-4">
          <p className="text-sm text-slate-700">
            Claude wants to use <span className="font-mono font-semibold">{r.tool}</span>{" "}
            outside the sandbox:
          </p>
          <pre className="my-2 overflow-auto rounded bg-white p-2 text-xs text-slate-800">
            {String(r.request.command ?? r.request.path ?? JSON.stringify(r.request))}
          </pre>
          <div className="flex justify-end gap-2">
            <button
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: executionId, requestId: r.id, decision: "deny" })}
            >
              Deny
            </button>
            <button
              className="rounded-md bg-orange-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-50"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: executionId, requestId: r.id, decision: "allow" })}
            >
              Allow
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}

function Review({
  task,
  progress,
  executionId,
}: {
  task: MetadataEntry;
  progress: ProgressState;
  executionId: string;
}) {
  const [feedback, setFeedback] = useState("");
  const sendFeedback = useSendFeedback();
  const createPr = useCreatePr();

  return (
    <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      {progress.doneSummary && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Summary
          </h3>
          <p className="text-sm text-slate-700">{progress.doneSummary}</p>
        </div>
      )}

      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Feedback
        </h3>
        <textarea
          className="w-full rounded-md border border-slate-300 p-2 text-sm"
          rows={3}
          placeholder="Ask for changes — Claude will resume and address them…"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
        />
        <div className="mt-2 flex justify-end">
          <button
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            disabled={sendFeedback.isPending || !feedback.trim()}
            onClick={() => {
              sendFeedback.mutate({ id: executionId, message: feedback.trim() });
              setFeedback("");
            }}
          >
            {sendFeedback.isPending ? "Sending…" : "Send feedback"}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3 border-t border-slate-100 pt-3">
        <button
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
          disabled={createPr.isPending}
          onClick={() => createPr.mutate({ id: executionId })}
        >
          {createPr.isPending ? "Creating PR…" : "Create PR"}
        </button>
        {createPr.isError && (
          <span className="text-sm text-red-600">{(createPr.error as Error).message}</span>
        )}
        {(task.relatedPrs ?? []).map((pr) => (
          <a
            key={pr.url}
            href={pr.url}
            target="_blank"
            rel="noreferrer"
            className="text-sm font-medium text-blue-600 hover:underline"
          >
            PR #{pr.number} ({pr.state})
          </a>
        ))}
      </div>
    </section>
  );
}
