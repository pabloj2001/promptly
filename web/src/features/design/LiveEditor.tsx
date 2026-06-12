import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Obsidian-style "live preview": the document stays rendered as Markdown, except the
// block the cursor is in, which becomes a raw-text <textarea>. Clicking another block
// renders the previous one and edits the new one; clicking outside renders everything.

interface Block {
  src: string;
  start: number;
  end: number;
  kind: "content" | "gap";
}

interface Sel {
  start: number;
  end: number;
}

// Split a document into contiguous blocks so blocks.map(b => b.src).join("") === body
// (exact offsets preserved for comment anchoring). Runs of blank lines become "gap"
// blocks; runs of non-blank lines (and fenced code, blanks included) become "content".
export function splitBlocks(body: string): Block[] {
  const lines: string[] = [];
  let i = 0;
  while (i < body.length) {
    const nl = body.indexOf("\n", i);
    if (nl === -1) {
      lines.push(body.slice(i));
      break;
    }
    lines.push(body.slice(i, nl + 1));
    i = nl + 1;
  }

  const blocks: Block[] = [];
  let buf = "";
  let bufStart = 0;
  let offset = 0;
  let curKind: "content" | "gap" | null = null;
  let inFence = false;

  const flush = () => {
    if (curKind === null) return;
    blocks.push({ src: buf, start: bufStart, end: bufStart + buf.length, kind: curKind });
    buf = "";
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const isFence = /^(```|~~~)/.test(trimmed);
    const kind: "content" | "gap" = trimmed === "" && !inFence ? "gap" : "content";

    if (curKind === null) {
      bufStart = offset;
      curKind = kind;
    } else if (kind !== curKind) {
      flush();
      bufStart = offset;
      curKind = kind;
    }
    buf += line;
    offset += line.length;
    if (isFence) inFence = !inFence;
  }
  flush();

  // Empty doc → a single editable content block so the user can start typing.
  if (blocks.length === 0) return [{ src: "", start: 0, end: 0, kind: "content" }];
  return blocks;
}

export function LiveEditor({
  value,
  onChange,
  onSelect,
}: {
  value: string;
  onChange: (full: string) => void;
  onSelect: (sel: Sel | null) => void;
}) {
  const [blocks, setBlocks] = useState<Block[]>(() => splitBlocks(value));
  const [active, setActive] = useState<number | null>(null);
  const lastEmitted = useRef(value);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // Re-split when the value changes from outside (Save / AI revision), not our own edit.
  useEffect(() => {
    if (value !== lastEmitted.current) {
      setBlocks(splitBlocks(value));
      lastEmitted.current = value;
      setActive(null);
    }
  }, [value]);

  // Click outside the editor → render everything.
  useEffect(() => {
    if (active === null) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setActive(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [active]);

  const blockStart = (idx: number) =>
    blocks.slice(0, idx).reduce((n, b) => n + b.src.length, 0);

  const editBlock = (idx: number, src: string) => {
    const next = blocks.map((b, i) => (i === idx ? { ...b, src } : b));
    setBlocks(next);
    const full = next.map((b) => b.src).join("");
    lastEmitted.current = full;
    onChange(full);
  };

  const captureSel = (idx: number) => {
    const ta = taRef.current;
    if (!ta) return;
    const s = ta.selectionStart;
    const e = ta.selectionEnd;
    if (e > s) {
      const base = blockStart(idx);
      onSelect({ start: base + s, end: base + e });
    } else {
      onSelect(null);
    }
  };

  return (
    <div ref={rootRef}>
      {blocks.map((b, i) => {
        if (b.kind === "gap") return <div key={i} className="h-3" />;
        if (i === active) {
          const rows = Math.max(1, b.src.replace(/\n$/, "").split("\n").length);
          return (
            <textarea
              key={i}
              ref={taRef}
              autoFocus
              rows={rows}
              className="w-full resize-none rounded border border-blue-300 bg-blue-50/30 p-2 font-mono text-sm leading-relaxed focus:border-blue-500 focus:outline-none"
              value={b.src}
              onChange={(e) => editBlock(i, e.target.value)}
              onSelect={() => captureSel(i)}
              onMouseUp={() => captureSel(i)}
              onKeyUp={() => captureSel(i)}
            />
          );
        }
        return (
          <div
            key={i}
            className="cursor-text rounded px-1 hover:bg-slate-50"
            onMouseDown={() => setActive(i)}
          >
            <article className="prose prose-slate max-w-none prose-pre:border prose-pre:border-slate-200 prose-pre:bg-slate-100 prose-pre:text-slate-800">
              <Markdown remarkPlugins={[remarkGfm]}>{b.src.trim() || " "}</Markdown>
            </article>
          </div>
        );
      })}
    </div>
  );
}
