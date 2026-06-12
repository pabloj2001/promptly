// Minimal unified-diff parser for the Build diff view (08). Turns `git diff`
// patch text into renderable lines, tracking old/new line numbers so comments
// can anchor to a specific {side, line}. Deliberately dependency-free and
// tolerant of binary/rename headers (rendered as meta lines).

export type DiffLineType = "add" | "del" | "context" | "hunk" | "meta";

export interface DiffLine {
  type: DiffLineType;
  text: string;
  oldLine?: number;
  newLine?: number;
}

const META_PREFIXES = [
  "diff ",
  "index ",
  "--- ",
  "+++ ",
  "new file",
  "deleted file",
  "old mode",
  "new mode",
  "rename ",
  "similarity ",
  "copy ",
  "Binary ",
  "GIT binary",
];

export function parseUnifiedDiff(patch: string): DiffLine[] {
  const out: DiffLine[] = [];
  let oldLn = 0;
  let newLn = 0;
  for (const line of patch.split("\n")) {
    if (line.startsWith("@@")) {
      const m = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      if (m) {
        oldLn = Number(m[1]);
        newLn = Number(m[2]);
      }
      out.push({ type: "hunk", text: line });
    } else if (META_PREFIXES.some((p) => line.startsWith(p))) {
      out.push({ type: "meta", text: line });
    } else if (line.startsWith("\\")) {
      out.push({ type: "meta", text: line }); // "\ No newline at end of file"
    } else if (line.startsWith("+")) {
      out.push({ type: "add", text: line.slice(1), newLine: newLn++ });
    } else if (line.startsWith("-")) {
      out.push({ type: "del", text: line.slice(1), oldLine: oldLn++ });
    } else {
      const text = line.startsWith(" ") ? line.slice(1) : line;
      out.push({ type: "context", text, oldLine: oldLn++, newLine: newLn++ });
    }
  }
  // Drop a trailing empty line produced by split on a trailing newline.
  if (out.length && out[out.length - 1].type === "context" && out[out.length - 1].text === "") {
    out.pop();
  }
  return out;
}

// The {side, line} a comment on this visual line should anchor to.
export function anchorFor(line: DiffLine): { side: "new" | "old"; line: number } | null {
  if (line.newLine != null && line.type !== "del") return { side: "new", line: line.newLine };
  if (line.oldLine != null) return { side: "old", line: line.oldLine };
  return null;
}
