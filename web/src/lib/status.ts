import type { TaskStatus } from "./types";

// Single source of truth for status colors + labels (reused by Plan graph/board
// and the Build sidebar). Static class strings so Tailwind keeps them.
export const STATUS_META: Record<
  TaskStatus,
  { label: string; badge: string; dot: string; surface: string }
> = {
  pending: {
    label: "Pending",
    badge: "bg-slate-100 text-slate-700",
    dot: "bg-slate-400",
    surface: "bg-slate-50 border-slate-300",
  },
  in_progress: {
    label: "In progress",
    badge: "bg-blue-100 text-blue-700",
    dot: "bg-blue-500",
    surface: "bg-blue-50 border-blue-300",
  },
  in_review: {
    label: "In review",
    badge: "bg-amber-100 text-amber-700",
    dot: "bg-amber-500",
    surface: "bg-amber-50 border-amber-300",
  },
  blocked: {
    label: "Blocked",
    badge: "bg-red-100 text-red-700",
    dot: "bg-red-500",
    surface: "bg-red-50 border-red-300",
  },
  done: {
    label: "Done",
    badge: "bg-green-100 text-green-700",
    dot: "bg-green-500",
    surface: "bg-green-50 border-green-300",
  },
  removed: {
    label: "Removed",
    badge: "bg-gray-100 text-gray-400",
    dot: "bg-gray-300",
    surface: "bg-gray-50 border-gray-200",
  },
};

export const STATUS_ORDER: TaskStatus[] = [
  "in_progress",
  "in_review",
  "blocked",
  "pending",
  "done",
];
