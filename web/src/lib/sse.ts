// EventSource helper for execution streams (04). Updates the React Query cache
// for an execution as `snapshot`/`step`/`question`/`permission`/`status` events
// arrive. Fully wired by Build (08); kept minimal here.

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUiStore } from "../store";
import type { ProgressState } from "./types";

/**
 * Subscribe to the per-project operations stream (03/05). On each `operation`
 * event, refresh the affected doc/task + lists so the Design loading states resolve
 * live. Subscribe once at the project level.
 */
export function useOperationsStream() {
  const qc = useQueryClient();
  const project = useUiStore((s) => s.activeProject);

  useEffect(() => {
    if (!project) return;
    const url = `/api/operations/stream?project=${encodeURIComponent(project)}`;
    const es = new EventSource(url);
    es.addEventListener("operation", (e) => {
      const data = JSON.parse((e as MessageEvent).data) as {
        entryId: string;
        collection: "docs" | "tasks";
      };
      qc.invalidateQueries({ queryKey: [data.collection, project] });
      qc.invalidateQueries({ queryKey: ["entry", project, data.collection, data.entryId] });
      qc.invalidateQueries({ queryKey: ["chat", project, data.collection, data.entryId] });
    });
    es.onerror = () => {
      /* EventSource auto-reconnects; nothing to do */
    };
    return () => es.close();
  }, [project, qc]);
}

/**
 * Subscribe to one execution's SSE stream (07/08). Every event carries the full
 * ProgressState, so we just write it into the `["execution", …]` cache. On a
 * status change we also refresh the task lists (task status flips with the run)
 * and the diff (a completed run adds a commit).
 */
export function useExecutionStream(executionId: string | null) {
  const qc = useQueryClient();
  const project = useUiStore((s) => s.activeProject);

  useEffect(() => {
    if (!executionId || !project) return;
    const url = `/api/executions/${executionId}/stream?project=${encodeURIComponent(
      project,
    )}`;
    const es = new EventSource(url);
    const key = ["execution", project, executionId];

    const setState = (e: Event) =>
      qc.setQueryData<ProgressState>(key, JSON.parse((e as MessageEvent).data));

    // Backend events (execution.py / internal router): every payload is a full
    // ProgressState snapshot.
    for (const name of ["snapshot", "steps", "question", "permission", "progress"]) {
      es.addEventListener(name, setState);
    }
    es.addEventListener("status", (e) => {
      setState(e);
      qc.invalidateQueries({ queryKey: ["tasks", project] });
      qc.invalidateQueries({ queryKey: ["taskGraph", project] });
      qc.invalidateQueries({ queryKey: ["diff", project, executionId] });
    });
    es.onerror = () => {
      /* EventSource auto-reconnects; the snapshot-on-connect re-syncs state */
    };

    return () => es.close();
  }, [executionId, project, qc]);
}
