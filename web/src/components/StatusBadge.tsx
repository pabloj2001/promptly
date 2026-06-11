import { STATUS_META } from "../lib/status";
import type { TaskStatus } from "../lib/types";

export function StatusBadge({ status }: { status?: TaskStatus | null }) {
  if (!status) return null;
  const meta = STATUS_META[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${meta.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  );
}
