import { useState } from "react";
import { STATUS_META } from "../lib/status";
import type { TaskStatus } from "../lib/types";

const DEFAULT_OPTIONS: TaskStatus[] = [
  "pending",
  "in_progress",
  "in_review",
  "blocked",
  "done",
];

// A status picker that shows the status color dot on the trigger and on every
// option (a native <select> can't color individual options reliably).
export function StatusSelect({
  value,
  onChange,
  options = DEFAULT_OPTIONS,
}: {
  value: TaskStatus;
  onChange: (status: TaskStatus) => void;
  options?: TaskStatus[];
}) {
  const [open, setOpen] = useState(false);
  const meta = STATUS_META[value];

  return (
    <div className="relative">
      <button
        type="button"
        className="mt-1 flex w-full items-center justify-between rounded border border-slate-300 px-2 py-1 text-sm hover:border-slate-400 focus:border-blue-500 focus:outline-none"
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />
          <span className="truncate">{meta.label}</span>
        </span>
        <span className="ml-2 text-slate-400">▾</span>
      </button>

      {open && (
        <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded border border-slate-200 bg-white shadow-lg">
          {options.map((s) => {
            const m = STATUS_META[s];
            return (
              <li key={s}>
                <button
                  type="button"
                  className={`flex w-full items-center gap-2 px-2 py-1 text-left text-sm hover:bg-slate-100 ${
                    s === value ? "bg-slate-50 font-medium" : ""
                  }`}
                  // onMouseDown (not onClick) so it fires before the trigger's
                  // onBlur closes the menu.
                  onMouseDown={(e) => {
                    e.preventDefault();
                    if (s !== value) onChange(s);
                    setOpen(false);
                  }}
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${m.dot}`} />
                  {m.label}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
