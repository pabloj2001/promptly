import { useEffect, useState } from "react";
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
import { ChatPanel } from "./ChatPanel";
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

  const op = data.meta.operation;
  const busy = op?.status === "running";
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
        collection, id: entry.id, commentId: id, patch: { resolved: true },
      });
    }
    setPreview(null);
  };

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
          <div className="flex gap-1">
            <ToggleBtn active={mode === "view"} onClick={() => setMode("view")}>
              View
            </ToggleBtn>
            <ToggleBtn
              active={mode === "edit"}
              onClick={() => !busy && setMode("edit")}
              disabled={busy}
            >
              Edit
            </ToggleBtn>
          </div>
          <div className="flex items-center gap-2">
            {addressError && <span className="text-xs text-red-600">{addressError}</span>}
            <button
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40"
              onClick={runAddress}
              disabled={addressing || busy || unresolved.length === 0}
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

        {/* In-progress banner for an existing doc being edited */}
        {busy && (
          <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
            <Spinner className="text-amber-600" />
            Changes in progress — editing is disabled until this finishes.
          </div>
        )}
        {op?.status === "failed" && (
          <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
            Last operation failed{op.error ? `: ${op.error}` : ""}.
          </div>
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

      {/* Address preview */}
      <Modal
        open={preview !== null}
        onOpenChange={(o) => !o && setPreview(null)}
        title="Proposed revision"
        description="The AI revised this document to address the comments. Accept to apply."
      >
        <div className="max-h-[50vh] overflow-auto rounded border border-slate-200 bg-slate-50 p-3">
          <article className="prose prose-slate prose-sm max-w-none prose-pre:border prose-pre:border-slate-200 prose-pre:bg-slate-100 prose-pre:text-slate-800">
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
