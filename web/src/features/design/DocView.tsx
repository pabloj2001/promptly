import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Spinner } from "../../components/Spinner";
import { type Collection } from "../../lib/api";
import {
  useAddComment,
  useAddressComments,
  useAnswerQuestion,
  useEntry,
  useExecution,
  useFollowupExecution,
  useResumeExecution,
  useSaveEntry,
  useUpdateComment,
} from "../../lib/queries";
import { useExecutionStream } from "../../lib/sse";
import type { Comment, MetadataEntry } from "../../lib/types";
import { collectionForType } from "./util";
import { ChatPanel } from "./ChatPanel";
import { DocDiff } from "./DocDiff";
import { LiveEditor } from "./LiveEditor";

export function DocView({ entry }: { entry: MetadataEntry }) {
  const collection: Collection = collectionForType(entry.type);
  const { data, isLoading } = useEntry(collection, entry.id);
  const save = useSaveEntry();
  const addComment = useAddComment();
  const updateComment = useUpdateComment();

  const [mode, setMode] = useState<"view" | "edit">("view");
  const [panel, setPanel] = useState<"chat" | "comments">("chat");
  const [draft, setDraft] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [sel, setSel] = useState<{ start: number; end: number } | null>(null);
  const [commentDraft, setCommentDraft] = useState("");

  // The entry's authoring execution (unified executions) drives the in-progress /
  // error / question UI, and the per-doc diff + follow-up after it completes.
  const authId = data?.meta.authoringExecutionId ?? null;
  useExecutionStream(authId);
  const { data: progress } = useExecution(authId);
  const address = useAddressComments();

  useEffect(() => {
    setDraft(data?.body ?? "");
    setMode("view");
    setSel(null);
  }, [data?.body, entry.id]);

  if (isLoading || !data) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <Spinner />
      </div>
    );
  }

  const busy = progress?.status === "running" || progress?.status === "awaiting_input";
  const isBlankNew = busy && !data.body.trim();

  // Brand-new doc still generating → blank loading state.
  if (isBlankNew) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-400">
        <Spinner className="text-slate-400" />
        <div>Generating <span className="font-medium">{data.meta.name}</span>…</div>
      </div>
    );
  }

  const comments = data.comments;
  const unresolved = comments.filter((c) => !c.resolved && !c.orphaned);
  const orphaned = comments.filter((c) => c.orphaned);

  const submitComment = () => {
    if (!sel || !commentDraft.trim()) return;
    const quote = draft.slice(sel.start, sel.end);
    addComment.mutate(
      {
        collection, id: entry.id,
        anchor: { quote, start: sel.start, end: sel.end },
        body: commentDraft.trim(), kind: "comment",
      },
      { onSuccess: () => { setCommentDraft(""); setSel(null); } },
    );
  };

  const askAi = () => {
    if (!sel) return;
    const quote = draft.slice(sel.start, sel.end);
    setPanel("chat");
    setChatInput(`Regarding "${quote}": `);
    setSel(null);
  };

  const saveAndView = async () => {
    try {
      if (draft !== data.body) {
        await save.mutateAsync({ collection, id: entry.id, body: draft });
      }
      setMode("view");
    } catch {
      // keep edit mode on failure
    }
  };

  return (
    <div className="flex h-full min-h-0">
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex items-center justify-end gap-2 border-b border-slate-200 px-4 py-2">
          {address.isError && (
            <span className="text-xs text-red-600">{(address.error as Error).message}</span>
          )}
          <button
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40"
            onClick={() => address.mutate({ collection, id: entry.id })}
            disabled={address.isPending || busy || unresolved.length === 0}
          >
            {address.isPending && <Spinner />}
            Address comments with AI
          </button>
        </div>

        {/* Authoring execution state (in-progress / awaiting / error / latest diff) */}
        {progress && authId && (
          <AuthoringBanner
            progress={progress}
            executionId={authId}
            entryName={data.meta.name}
          />
        )}

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-auto p-6">
          {mode === "view" || busy ? (
            <article className="prose prose-slate max-w-none prose-pre:border prose-pre:border-slate-200 prose-pre:bg-slate-100 prose-pre:text-slate-800">
              <Markdown remarkPlugins={[remarkGfm]}>{data.body || "*(empty)*"}</Markdown>
            </article>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">
                Click a block to edit it in place; select text to comment or ask the AI
                (right panel).
              </p>
              <LiveEditor value={draft} onChange={setDraft} onSelect={setSel} />
            </div>
          )}
        </div>

        {/* Floating edit / save-and-view button */}
        {!busy && (
          <button
            className="absolute bottom-5 right-5 flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-white shadow-lg hover:bg-blue-700 disabled:opacity-50"
            onClick={mode === "view" ? () => setMode("edit") : saveAndView}
            disabled={save.isPending}
            title={mode === "view" ? "Edit" : "Save & view"}
          >
            {save.isPending ? (
              <Spinner />
            ) : mode === "view" ? (
              <PencilIcon />
            ) : (
              <CheckIcon />
            )}
          </button>
        )}
      </div>

      {/* Right panel: Chat / Comments */}
      <div className="flex w-96 flex-col border-l border-slate-200 bg-slate-50">
        <div className="flex gap-1 border-b border-slate-200 p-2">
          <ToggleBtn active={panel === "chat"} onClick={() => setPanel("chat")}>
            Chat
          </ToggleBtn>
          <ToggleBtn active={panel === "comments"} onClick={() => setPanel("comments")}>
            Comments{unresolved.length ? ` (${unresolved.length})` : ""}
          </ToggleBtn>
        </div>

        {panel === "chat" ? (
          <ChatPanel
            collection={collection}
            entryId={entry.id}
            value={chatInput}
            onChange={setChatInput}
            busy={!!busy}
          />
        ) : (
          <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
            {mode === "edit" && sel && !busy && (
              <div className="rounded-md border border-blue-200 bg-blue-50 p-2">
                <div className="mb-1 truncate text-xs italic text-slate-500">
                  “{draft.slice(sel.start, sel.end)}”
                </div>
                <textarea
                  className="w-full resize-none rounded border border-slate-300 p-1.5 text-sm"
                  rows={2}
                  value={commentDraft}
                  onChange={(e) => setCommentDraft(e.target.value)}
                  placeholder="Add a comment…"
                />
                <div className="mt-1 flex gap-1">
                  <button
                    className="flex-1 rounded bg-slate-600 px-2 py-1 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
                    onClick={submitComment}
                    disabled={!commentDraft.trim() || addComment.isPending}
                  >
                    Comment
                  </button>
                  <button
                    className="flex-1 rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700"
                    onClick={askAi}
                  >
                    Ask AI
                  </button>
                </div>
              </div>
            )}

            {comments.length === 0 && (
              <p className="text-sm text-slate-400">No comments yet.</p>
            )}
            {unresolved.map((c) => (
              <CommentCard
                key={c.id}
                comment={c}
                onResolve={() =>
                  updateComment.mutate({
                    collection, id: entry.id, commentId: c.id, patch: { resolved: true },
                  })
                }
              />
            ))}

            {comments.some((c) => c.resolved) && (
              <details className="text-xs text-slate-500">
                <summary className="cursor-pointer">Resolved</summary>
                <div className="mt-1 space-y-2">
                  {comments.filter((c) => c.resolved).map((c) => (
                    <CommentCard key={c.id} comment={c} resolved />
                  ))}
                </div>
              </details>
            )}

            {orphaned.length > 0 && (
              <details className="text-xs text-amber-700" open>
                <summary className="cursor-pointer">Orphaned ({orphaned.length})</summary>
                <div className="mt-1 space-y-2">
                  {orphaned.map((c) => (
                    <CommentCard key={c.id} comment={c} />
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// In-progress / awaiting-input / error / completed-with-diff banner for a doc's
// authoring execution. Lives inline in the Design tab (unified executions).
function AuthoringBanner({
  progress,
  executionId,
  entryName,
}: {
  progress: import("../../lib/types").ProgressState;
  executionId: string;
  entryName: string;
}) {
  const resume = useResumeExecution();
  const answer = useAnswerQuestion();
  const followup = useFollowupExecution();
  const [reply, setReply] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [showDiff, setShowDiff] = useState(false);

  const openQuestion = progress.pendingQuestions.find((q) => q.answer == null);

  if (progress.status === "running") {
    return (
      <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
        <div className="flex items-center gap-2">
          <Spinner className="text-amber-600" />
          <span className="font-medium">{entryName}</span> — working… editing is disabled.
        </div>
        {progress.activity && (
          <div className="mt-0.5 truncate text-xs text-amber-700/80">{progress.activity}</div>
        )}
      </div>
    );
  }

  if (progress.status === "awaiting_input" && openQuestion) {
    return (
      <div className="border-b border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <div className="mb-1 font-semibold">Claude has a question</div>
        <p className="mb-2 whitespace-pre-wrap">{openQuestion.question}</p>
        <textarea
          className="w-full rounded border border-amber-300 p-1.5 text-sm"
          rows={2}
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          placeholder="Type your answer…"
        />
        <div className="mt-1 flex justify-end">
          <button
            className="rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
            disabled={!reply.trim() || answer.isPending}
            onClick={() => {
              answer.mutate({ id: executionId, questionId: openQuestion.id, answer: reply.trim() });
              setReply("");
            }}
          >
            {answer.isPending ? "Sending…" : "Send answer"}
          </button>
        </div>
      </div>
    );
  }

  if (progress.status === "failed") {
    return (
      <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
        <span className="font-medium">Authoring failed</span>
        {progress.error ? `: ${progress.error}` : "."}{" "}
        <button
          className="ml-1 rounded bg-red-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
          disabled={resume.isPending}
          onClick={() => resume.mutate(executionId)}
        >
          {resume.isPending ? "Retrying…" : "Try again"}
        </button>
      </div>
    );
  }

  // completed: offer the per-doc diff + a follow-up.
  return (
    <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
      <div className="flex items-center gap-3">
        <button
          className="text-xs font-medium text-blue-700 hover:underline"
          onClick={() => setShowDiff((s) => !s)}
        >
          {showDiff ? "Hide changes" : "View changes"}
        </button>
        <input
          className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
          value={followUp}
          onChange={(e) => setFollowUp(e.target.value)}
          placeholder="Follow up — ask for more changes…"
          onKeyDown={(e) => {
            if (e.key === "Enter" && followUp.trim()) {
              followup.mutate({ id: executionId, message: followUp.trim() });
              setFollowUp("");
            }
          }}
        />
        <button
          className="rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          disabled={!followUp.trim() || followup.isPending}
          onClick={() => {
            followup.mutate({ id: executionId, message: followUp.trim() });
            setFollowUp("");
          }}
        >
          {followup.isPending ? "…" : "Follow up"}
        </button>
      </div>
      {showDiff && (
        <div className="mt-2">
          <DocDiff executionId={executionId} />
        </div>
      )}
    </div>
  );
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden>
      <path d="M13.586 3.586a2 2 0 112.828 2.828l-8.5 8.5a2 2 0 01-.878.512l-3.2.914a.5.5 0 01-.618-.618l.914-3.2a2 2 0 01.512-.878l8.5-8.5z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2.5}
         strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
      <path d="M4 10.5l4 4 8-9" />
    </svg>
  );
}

function ToggleBtn({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      className={`rounded px-2.5 py-1 text-sm font-medium disabled:opacity-40 ${
        active ? "bg-blue-100 text-blue-700" : "text-slate-600 hover:bg-slate-100"
      }`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function CommentCard({
  comment,
  resolved,
  onResolve,
}: {
  comment: Comment;
  resolved?: boolean;
  onResolve?: () => void;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-2 text-sm">
      <div className="mb-1 flex items-center justify-between">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
          {comment.kind}
        </span>
        {onResolve && (
          <button className="text-xs text-blue-600 hover:underline" onClick={onResolve}>
            Resolve
          </button>
        )}
      </div>
      <div className="truncate text-xs italic text-slate-500">“{comment.anchor.quote}”</div>
      <div className={`mt-1 ${resolved ? "text-slate-400 line-through" : "text-slate-700"}`}>
        {comment.body}
      </div>
    </div>
  );
}
