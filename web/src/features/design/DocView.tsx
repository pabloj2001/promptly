import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { api, type Collection } from "../../lib/api";
import {
  useAddComment,
  useEntry,
  useSaveEntry,
  useUpdateComment,
} from "../../lib/queries";
import type { Comment, MetadataEntry } from "../../lib/types";
import { collectionForType } from "./util";

export function DocView({ entry }: { entry: MetadataEntry }) {
  const collection: Collection = collectionForType(entry.type);
  const { data, isLoading } = useEntry(collection, entry.id);
  const save = useSaveEntry();
  const addComment = useAddComment();
  const updateComment = useUpdateComment();

  const [mode, setMode] = useState<"view" | "edit">("view");
  const [draft, setDraft] = useState("");
  const [sel, setSel] = useState<{ start: number; end: number } | null>(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [commentKind, setCommentKind] = useState<"comment" | "question">("comment");
  const taRef = useRef<HTMLTextAreaElement>(null);

  // Address-with-AI preview state.
  const [addressing, setAddressing] = useState(false);
  const [preview, setPreview] = useState<{ body: string; ids: string[] } | null>(null);
  const [addressError, setAddressError] = useState<string | null>(null);

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

  const comments = data.comments;
  const unresolved = comments.filter((c) => !c.resolved && !c.orphaned);
  const orphaned = comments.filter((c) => c.orphaned);

  const captureSelection = () => {
    const ta = taRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    setSel(end > start ? { start, end } : null);
  };

  const submitComment = () => {
    if (!sel || !commentDraft.trim()) return;
    const quote = draft.slice(sel.start, sel.end);
    addComment.mutate(
      {
        collection,
        id: entry.id,
        anchor: { quote, start: sel.start, end: sel.end },
        body: commentDraft.trim(),
        kind: commentKind,
      },
      {
        onSuccess: () => {
          setCommentDraft("");
          setSel(null);
        },
      },
    );
  };

  const saveBody = () => save.mutate({ collection, id: entry.id, body: draft });

  const runAddress = async () => {
    setAddressing(true);
    setAddressError(null);
    try {
      const res = await api.address(collection, entry.id);
      setPreview({ body: res.revisedBody, ids: res.addressedCommentIds });
    } catch (e) {
      setAddressError(e instanceof Error ? e.message : "Address failed");
    } finally {
      setAddressing(false);
    }
  };

  const acceptAddress = async () => {
    if (!preview) return;
    await save.mutateAsync({ collection, id: entry.id, body: preview.body });
    for (const id of preview.ids) {
      await updateComment.mutateAsync({
        collection,
        id: entry.id,
        commentId: id,
        patch: { resolved: true },
      });
    }
    setPreview(null);
  };

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-h-0 flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
          <div className="flex gap-1">
            <ToggleBtn active={mode === "view"} onClick={() => setMode("view")}>
              View
            </ToggleBtn>
            <ToggleBtn active={mode === "edit"} onClick={() => setMode("edit")}>
              Edit
            </ToggleBtn>
          </div>
          <div className="flex items-center gap-2">
            {addressError && <span className="text-xs text-red-600">{addressError}</span>}
            <button
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40"
              onClick={runAddress}
              disabled={addressing || unresolved.length === 0}
              title={
                unresolved.length === 0 ? "No unresolved comments" : "Let AI revise"
              }
            >
              {addressing && <Spinner />}
              Address comments with AI
            </button>
            {mode === "edit" && (
              <button
                className="rounded-md bg-blue-600 px-2.5 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                onClick={saveBody}
                disabled={save.isPending || draft === data.body}
              >
                Save
              </button>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-auto p-6">
          {mode === "view" ? (
            <article className="prose prose-slate max-w-none prose-headings:font-semibold prose-pre:bg-slate-100">
              <Markdown remarkPlugins={[remarkGfm]}>{data.body || "*(empty)*"}</Markdown>
            </article>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">
                Select text below, then add a comment or question in the panel on the right.
              </p>
              <textarea
                ref={taRef}
                className="h-[60vh] w-full resize-none rounded-md border border-slate-300 p-3 font-mono text-sm focus:border-blue-500 focus:outline-none"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onSelect={captureSelection}
                onMouseUp={captureSelection}
                onKeyUp={captureSelection}
              />
            </div>
          )}
        </div>
      </div>

      {/* Comments panel */}
      <div className="flex w-80 flex-col border-l border-slate-200 bg-slate-50">
        <div className="border-b border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700">
          Comments
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
          {mode === "edit" && sel && (
            <div className="rounded-md border border-blue-200 bg-blue-50 p-2">
              <div className="mb-1 truncate text-xs italic text-slate-500">
                “{draft.slice(sel.start, sel.end)}”
              </div>
              <div className="mb-1 flex gap-1 text-xs">
                <ToggleBtn
                  active={commentKind === "comment"}
                  onClick={() => setCommentKind("comment")}
                >
                  Comment
                </ToggleBtn>
                <ToggleBtn
                  active={commentKind === "question"}
                  onClick={() => setCommentKind("question")}
                >
                  Ask AI
                </ToggleBtn>
              </div>
              <textarea
                className="w-full resize-none rounded border border-slate-300 p-1.5 text-sm"
                rows={2}
                value={commentDraft}
                onChange={(e) => setCommentDraft(e.target.value)}
                placeholder="Your note…"
              />
              <button
                className="mt-1 w-full rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                onClick={submitComment}
                disabled={!commentDraft.trim() || addComment.isPending}
              >
                Add {commentKind === "question" ? "question" : "comment"}
              </button>
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
                  collection,
                  id: entry.id,
                  commentId: c.id,
                  patch: { resolved: true },
                })
              }
            />
          ))}

          {comments.some((c) => c.resolved) && (
            <details className="text-xs text-slate-500">
              <summary className="cursor-pointer">Resolved</summary>
              <div className="mt-1 space-y-2">
                {comments
                  .filter((c) => c.resolved)
                  .map((c) => (
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
      </div>

      {/* Address preview */}
      <Modal
        open={preview !== null}
        onOpenChange={(o) => !o && setPreview(null)}
        title="Proposed revision"
        description="The AI revised this document to address the comments. Accept to apply."
      >
        <div className="max-h-[50vh] overflow-auto rounded border border-slate-200 bg-slate-50 p-3">
          <article className="prose prose-sm max-w-none">
            <Markdown remarkPlugins={[remarkGfm]}>{preview?.body ?? ""}</Markdown>
          </article>
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <button
            className="rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
            onClick={() => setPreview(null)}
          >
            Reject
          </button>
          <button
            className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
            onClick={acceptAddress}
          >
            Accept
          </button>
        </div>
      </Modal>
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
      className={`rounded px-2.5 py-1 text-sm font-medium ${
        active ? "bg-blue-100 text-blue-700" : "text-slate-600 hover:bg-slate-100"
      }`}
      onClick={onClick}
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
        <span
          className={`rounded px-1.5 py-0.5 text-xs ${
            comment.kind === "question"
              ? "bg-purple-100 text-purple-700"
              : "bg-slate-100 text-slate-600"
          }`}
        >
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
