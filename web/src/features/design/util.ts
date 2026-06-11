import type { Collection } from "../../lib/api";
import type { DocType } from "../../lib/types";

export function collectionForType(type: DocType): Collection {
  return type === "task" ? "tasks" : "docs";
}
