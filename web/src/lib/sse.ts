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

    const merge = (patch: Partial<ProgressState>) =>
      qc.setQueryData<ProgressState>(key, (prev) =>
        prev ? { ...prev, ...patch } : (patch as ProgressState),
      );

    es.addEventListener("snapshot", (e) =>
      qc.setQueryData(key, JSON.parse((e as MessageEvent).data)),
    );
    es.addEventListener("status", (e) => merge(JSON.parse((e as MessageEvent).data)));
    // step/question/permission events trigger a refetch of the full snapshot via
    // the next GET; Build (08) will refine this into granular cache updates.
    const refetch = () => qc.invalidateQueries({ queryKey: key });
    es.addEventListener("step", refetch);
    es.addEventListener("question", refetch);
    es.addEventListener("permission", refetch);
    es.onerror = () => es.close();

    return () => es.close();
  }, [executionId, project, qc]);
}
