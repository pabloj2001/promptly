import { create } from "zustand";

// Small cross-cutting UI state (04). Server data lives in React Query.
type PlanView = "graph" | "board";

interface UiState {
  activeProject: string | null;
  selectedTaskId: string | null;
  planView: PlanView;
  setActiveProject: (name: string | null) => void;
  setSelectedTaskId: (id: string | null) => void;
  setPlanView: (v: PlanView) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activeProject: null,
  selectedTaskId: null,
  planView: "graph",
  setActiveProject: (name) => set({ activeProject: name }),
  setSelectedTaskId: (id) => set({ selectedTaskId: id }),
  setPlanView: (v) => set({ planView: v }),
}));

// Non-hook accessor so the API client can read the active project outside React.
export const getActiveProject = () => useUiStore.getState().activeProject;
