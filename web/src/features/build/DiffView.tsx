import { useEffect, useState } from "react";
import {
  useAddDiffComment,
  useDiff,
  useDiffComments,
  useUpdateDiffComment,
} from "../../lib/queries";
import type { DiffComment } from "../../lib/types";
import { anchorFor, parseUnifiedDiff, type DiffLine } from "./diff";

// Diff view (08): file list + unified diff with per-line comments, partitioned
// by the commit they were written against (older commits collapsible).
export function DiffView({ executionId }: { executionId: string }) {
  const { data: diff, isLoading } = useDiff(executionId);
  const { data: comments } = useDiffComments(executionId);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (diff && diff.files.length && !diff.files.some((f) => f.path === selected)) {
      setSelected(diff.files[0].path);
    }
  }, [diff, selected]);

  if (isLoading) return <p className="p-4 text-sm text-slate-400">Loading diff…</p>;
  if (!diff || diff.files.length === 0)
    return <p className="p-4 text-sm text-slate-400">No changes yet.</p>;

  const file = diff.files.find((f) => f.path === selected) ?? diff.files[0];

  return (
    <div className="flex h-full">
      <div className="w-64 shrink-0 overflow-auto border-r border-slate-200 bg-slate-50">
        <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Changed files
        </div>
        {diff.files.map((f) => (
          <button
            key={f.path}
            className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm ${
              f.path === file.path ? "bg-blue-100 text-blue-800" : "text-slate-700 hover:bg-slate-100"
            }`}
            onClick={() => setSelected(f.path)}
          >
            <span className="w-4 shrink-0 text-center text-xs text-slate-400">{f.status}</span>
            <span className="min-w-0 flex-1 truncate font-mono text-xs">{f.path}</span>
          </button>
        ))}
      </div>
      <div className="min-w-0 flex-1 overflow-auto">
        <FileDiff
          executionId={executionId}
          file={file.path}
          patch={file.diff}
          headSha={diff.headSha}
          comments={comments?.byCommit ?? {}}
        />
      </div>
    </div>
  );
}

function FileDiff({
  executionId,
  file,
  patch,
  headSha,
  comments,
}: {
  executionId: string;
  file: string;
  patch: string;
  headSha: string;
  comments: Record<string, DiffComment[]>;
}) {
  const lines = parseUnifiedDiff(patch);
  const addComment = useAddDiffComment();
  const [composing, setComposing] = useState<{ side: "new" | "old"; line: number } | null>(null);
  const [text, setText] = useState("");

  // Current-commit comments for this file, indexed by side:line.
  const current = (comments[headSha] ?? []).filter((c) => c.file === file);
  const byLine: Record<string, DiffComment[]> = {};
  for (const c of current) (byLine[`${c.side}:${c.lineStart}`] ??= []).push(c);

  const older = Object.entries(comments)
    .filter(([sha]) => sha !== headSha)
    .flatMap(([sha, list]) => list.filter((c) => c.file === file).map((c) => ({ sha, c })));

  const submit = () => {
    if (!composing || !text.trim()) return;
    addComment.mutate({
      id: executionId,
      comment: {
        commit: headSha,
        file,
        side: composing.side,
        lineStart: composing.line,
        lineEnd: composing.line,
        body: text.trim(),
      },
    });
    setText("");
    setComposing(null);
  };

  return (
    <div className="font-mono text-xs">
      {lines.map((ln, i) => {
        const a = anchorFor(ln);
        const key = a ? `${a.side}:${a.line}` : "";
        const lineComments = a ? byLine[key] ?? [] : [];
        const isComposing = a && composing?.side === a.side && composing?.line === a.line;
        return (
          <div key={i}>
            <Line line={ln} onComment={a ? () => setComposing(a) : undefined} />
            {lineComments.map((c) => (
              <CommentRow key={c.id} executionId={executionId} comment={c} />
            ))}
            {isComposing && (
              <div className="border-y border-blue-200 bg-blue-50 px-3 py-2">
                <textarea
                  autoFocus
                  className="w-full rounded border border-slate-300 p-2 font-sans text-sm"
                  rows={2}
                  placeholder="Comment on this line…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <div className="mt-1 flex justify-end gap-2 font-sans">
                  <button
                    className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-200"
                    onClick={() => {
                      setComposing(null);
                      setText("");
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    disabled={addComment.isPending || !text.trim()}
                    onClick={submit}
                  >
                    Comment
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {older.length > 0 && <OlderComments executionId={executionId} items={older} />}
    </div>
  );
}

function Line({ line, onComment }: { line: DiffLine; onComment?: () => void }) {
  const bg =
    line.type === "add"
      ? "bg-green-50"
      : line.type === "del"
        ? "bg-red-50"
        : line.type === "hunk"
          ? "bg-slate-100 text-slate-500"
          : line.type === "meta"
            ? "bg-slate-50 text-slate-400"
            : "";
  const sign = line.type === "add" ? "+" : line.type === "del" ? "-" : " ";
  return (
    <div className={`group flex items-start ${bg}`}>
      <span className="w-10 shrink-0 select-none px-1 text-right text-slate-400">
        {line.oldLine ?? ""}
      </span>
      <span className="w-10 shrink-0 select-none px-1 text-right text-slate-400">
        {line.newLine ?? ""}
      </span>
      {onComment ? (
        <button
          className="w-5 shrink-0 select-none text-center text-slate-300 opacity-0 hover:text-blue-600 group-hover:opacity-100"
          title="Comment on this line"
          onClick={onComment}
        >
          +
        </button>
      ) : (
        <span className="w-5 shrink-0" />
      )}
      <span className="w-3 shrink-0 select-none text-slate-400">{sign}</span>
      <span className="whitespace-pre-wrap break-all">{line.text}</span>
    </div>
  );
}

function CommentRow({ executionId, comment }: { executionId: string; comment: DiffComment }) {
  const update = useUpdateDiffComment();
  return (
    <div
      className={`border-y border-slate-200 bg-white px-3 py-2 font-sans text-sm ${
        comment.resolved ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-start gap-2">
        <span className="flex-1">
          <span className="mr-2 text-xs font-semibold text-slate-500">{comment.author}</span>
          {comment.body}
        </span>
        <button
          className="shrink-0 text-xs font-medium text-slate-500 hover:text-slate-800"
          onClick={() =>
            update.mutate({
              id: executionId,
              commentId: comment.id,
              patch: { resolved: !comment.resolved },
            })
          }
        >
          {comment.resolved ? "Reopen" : "Resolve"}
        </button>
      </div>
    </div>
  );
}

function OlderComments({
  executionId,
  items,
}: {
  executionId: string;
  items: { sha: string; c: DiffComment }[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4 border-t border-slate-200 font-sans">
      <button
        className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-600"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "▾" : "▸"} Comments on earlier commits ({items.length})
      </button>
      {open &&
        items.map(({ sha, c }) => (
          <div key={c.id} className="px-3 py-1.5 text-sm text-slate-600">
            <span className="mr-2 font-mono text-xs text-slate-400">
              {sha.slice(0, 7)} · {c.side} L{c.lineStart}
            </span>
            {c.body}
            {!c.resolved && <ResolveLink executionId={executionId} comment={c} />}
          </div>
        ))}
    </div>
  );
}

function ResolveLink({ executionId, comment }: { executionId: string; comment: DiffComment }) {
  const update = useUpdateDiffComment();
  return (
    <button
      className="ml-2 text-xs font-medium text-slate-500 hover:text-slate-800"
      onClick={() =>
        update.mutate({ id: executionId, commentId: comment.id, patch: { resolved: true } })
      }
    >
      Resolve
    </button>
  );
}
