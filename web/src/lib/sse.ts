// EventSource helper for execution streams (04). Updates the React Query cache
// for an execution as `snapshot`/`step`/`question`/`permission`/`status` events
// arrive. Fully wired by Build (08); kept minimal here.

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUiStore } from "../store";
import type { ProgressState } from "./types";

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
      // A status change can flip a task status, finalize a doc body, or update the
      // executions list — refresh the lists + this execution's diff. (Doc-authoring
      // executions live in the Design tab too, so refresh docs as well.)
      const data = JSON.parse((e as MessageEvent).data) as ProgressState;
      qc.invalidateQueries({ queryKey: ["tasks", project] });
      qc.invalidateQueries({ queryKey: ["taskGraph", project] });
      qc.invalidateQueries({ queryKey: ["docs", project] });
      qc.invalidateQueries({ queryKey: ["executions", project] });
      qc.invalidateQueries({ queryKey: ["diff", project, executionId] });
      qc.invalidateQueries({
        queryKey: ["entry", project, data.collection, data.taskId],
      });
      qc.invalidateQueries({ queryKey: ["chat", project, data.collection, data.taskId] });
    });
    es.onerror = () => {
      /* EventSource auto-reconnects; the snapshot-on-connect re-syncs state */
    };

    return () => es.close();
  }, [executionId, project, qc]);
}
